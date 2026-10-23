using FinAgent.Api.Data;
using FinAgent.Api.DTOs;
using FinAgent.Api.Entities;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;

namespace FinAgent.Api.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class PortfolioAnalysisController : ControllerBase
    {
        private readonly AppDbContext _context;
        private readonly IHttpClientFactory _httpClientFactory;
        private readonly IConfiguration _configuration;

        public PortfolioAnalysisController(
            AppDbContext context, 
            IHttpClientFactory httpClientFactory, 
            IConfiguration configuration)
        {
            _context = context;
            _httpClientFactory = httpClientFactory;
            _configuration = configuration;
        }

        // Kur Geçerlilik Doğrulayıcı (342.00 TL gibi hatalı girişleri önler)
        private static decimal ValidateFxRate(string ticker, decimal inputFx, decimal fallbackUsdTry = 49.55m)
        {
            if (ticker.EndsWith(".IS")) return 1.0m;
            if (inputFx < 2.0m || inputFx > 100.0m) return fallbackUsdTry;
            return inputFx;
        }

        // 1. Portföyü getir (Varsa çift kayıtları otomatik birleştirir)
        [HttpGet("portfolio")]
        public async Task<IActionResult> GetPortfolio()
        {
            var allItems = await _context.PortfolioItems
                .Include(p => p.AnalysisJobs)
                .ToListAsync();

            bool dbModified = false;

            // Veritabanında kalmış hatalı alış kurlarını düzelt
            foreach (var item in allItems)
            {
                var validFx = ValidateFxRate(item.TickerSymbol, item.AverageFxRate);
                if (item.AverageFxRate != validFx)
                {
                    item.AverageFxRate = validFx;
                    dbModified = true;
                }
            }

            // Aynı sembolleri ağırlıklı ortalama maliyetle otomatik birleştir
            var duplicateGroups = allItems.GroupBy(x => x.TickerSymbol.ToUpper().Trim())
                                          .Where(g => g.Count() > 1)
                                          .ToList();

            if (duplicateGroups.Any())
            {
                foreach (var group in duplicateGroups)
                {
                    var primary = group.First();
                    var others = group.Skip(1).ToList();

                    foreach (var dup in others)
                    {
                        var totalCost = (primary.Quantity * primary.AverageCost) + (dup.Quantity * dup.AverageCost);
                        primary.Quantity += dup.Quantity;
                        primary.AverageCost = primary.Quantity > 0 ? totalCost / primary.Quantity : 0;

                        // Eski kaydın raporlarını ana kayda taşı
                        foreach (var job in dup.AnalysisJobs)
                        {
                            job.PortfolioItemId = primary.Id;
                        }
                        _context.PortfolioItems.Remove(dup);
                    }
                }
                dbModified = true;
            }

            if (dbModified) await _context.SaveChangesAsync();

            var cleanItems = await _context.PortfolioItems
                .Include(p => p.AnalysisJobs.OrderByDescending(j => j.CreatedAt).Take(10))
                .OrderBy(p => p.TickerSymbol)
                .ToListAsync();

            return Ok(cleanItems);
        }

        // 2. Portföye hisse ekle (Aynı sembol varsa ağırlıklı ortalama maliyetle birleştirir)
        [HttpPost("portfolio")]
        public async Task<IActionResult> AddPortfolioItem([FromBody] CreatePortfolioItemDto dto)
        {
            var normalizedTicker = dto.TickerSymbol.ToUpper().Trim();
            var fx = ValidateFxRate(normalizedTicker, dto.PurchaseFxRate);

            var existingItem = await _context.PortfolioItems
                .FirstOrDefaultAsync(p => p.TickerSymbol == normalizedTicker);

            if (existingItem != null)
            {
                var oldCostNative = existingItem.Quantity * existingItem.AverageCost;
                var newCostNative = dto.Quantity * dto.AverageCost;

                var oldFx = ValidateFxRate(normalizedTicker, existingItem.AverageFxRate);
                var oldCostTry = oldCostNative * oldFx;
                var newCostTry = newCostNative * fx;

                existingItem.Quantity += dto.Quantity;
                if (existingItem.Quantity > 0 && (oldCostNative + newCostNative) > 0)
                {
                    existingItem.AverageCost = (oldCostNative + newCostNative) / existingItem.Quantity;
                    existingItem.AverageFxRate = ValidateFxRate(normalizedTicker, (oldCostTry + newCostTry) / (oldCostNative + newCostNative));
                }

                await _context.SaveChangesAsync();
                return Ok(existingItem);
            }

            var item = new PortfolioItem
            {
                TickerSymbol = normalizedTicker,
                Quantity = dto.Quantity,
                AverageCost = dto.AverageCost,
                AverageFxRate = fx
            };

            _context.PortfolioItems.Add(item);
            await _context.SaveChangesAsync();
            return Ok(item);
        }

        // Pozisyon maliyet, adet ve alış kurunu elle düzeltme
        [HttpPut("portfolio/{id}")]
        public async Task<IActionResult> UpdatePortfolioItem(int id, [FromBody] UpdatePortfolioItemDto dto)
        {
            var item = await _context.PortfolioItems.FindAsync(id);
            if (item == null) return NotFound("Pozisyon bulunamadı.");

            item.Quantity = dto.Quantity;
            item.AverageCost = dto.AverageCost;
            item.AverageFxRate = ValidateFxRate(item.TickerSymbol, dto.PurchaseFxRate);

            await _context.SaveChangesAsync();
            return Ok(item);
        }

        // YENİ: Kısmi Satış / Pozisyon Azaltma ve Gerçekleşmiş K/Z (Realized P&L) Hesabı
        [HttpPost("portfolio/{id}/sell")]
        public async Task<IActionResult> SellPortfolioItem(int id, [FromBody] SellPortfolioItemDto dto)
        {
            var item = await _context.PortfolioItems.FindAsync(id);
            if (item == null) return NotFound("Pozisyon bulunamadı.");
            if (dto.QuantityToSell <= 0 || dto.QuantityToSell > item.Quantity)
                return BadRequest("Geçersiz satış adedi.");

            var saleFx = ValidateFxRate(item.TickerSymbol, dto.CurrentFxRate);
            var buyFx = ValidateFxRate(item.TickerSymbol, item.AverageFxRate);

            // Satılan kısmın TRY geliri - Satılan kısmın alış kurundaki TRY maliyeti
            var saleProceedsTry = dto.QuantityToSell * dto.SalePrice * saleFx;
            var costBasisTry = dto.QuantityToSell * item.AverageCost * buyFx;
            item.RealizedPnlTry += (saleProceedsTry - costBasisTry);

            item.Quantity -= dto.QuantityToSell;

            await _context.SaveChangesAsync();
            return Ok(item);
        }

        // 3. Portföyden hisse sil
        [HttpDelete("portfolio/{id}")]
        public async Task<IActionResult> DeletePortfolioItem(int id)
        {
            var item = await _context.PortfolioItems.FindAsync(id);
            if (item == null) return NotFound();

            _context.PortfolioItems.Remove(item);
            await _context.SaveChangesAsync();
            return NoContent();
        }

        // 4. Asenkron Analiz Başlat
        [HttpPost("analyze/{portfolioItemId}")]
        public async Task<IActionResult> StartAnalysisJob(int portfolioItemId, [FromBody] StartAnalyzeContextDto? ctx)
        {
            var item = await _context.PortfolioItems.FindAsync(portfolioItemId);
            if (item == null) return NotFound("Portföy kalemi bulunamadı.");

            var totalCount = await _context.PortfolioItems.CountAsync();

            var job = new AnalysisJob
            {
                PortfolioItemId = item.Id,
                TickerSymbol = item.TickerSymbol,
                Status = "Paralel Ajanlar Başlatılıyor...",
                CreatedAt = DateTime.UtcNow
            };

            _context.AnalysisJobs.Add(job);
            await _context.SaveChangesAsync();

            var pythonBaseUrl = _configuration["PythonAiService:BaseUrl"] ?? "http://localhost:8000";
            var client = _httpClientFactory.CreateClient();

            try
            {
                var payload = new TriggerPythonJobRequest(
                    job.Id,
                    job.TickerSymbol,
                    ctx?.PortfolioWeightPct ?? 0,
                    ctx?.MaxPortfolioWeightPct ?? (ctx?.PortfolioWeightPct ?? 0),
                    ctx?.LargestPositionTicker ?? item.TickerSymbol,
                    ctx?.EffectiveN ?? 1.0,
                    ctx?.TotalPositionsCount ?? totalCount,
                    item.Quantity,
                    item.AverageCost,
                    ctx?.PnlPct ?? 0
                );
                var response = await client.PostAsJsonAsync($"{pythonBaseUrl}/api/agent/analyze", payload);

                if (!response.IsSuccessStatusCode)
                {
                    job.Status = "Failed";
                    job.ErrorMessage = $"Python servisi hata döndü: {response.StatusCode}";
                    await _context.SaveChangesAsync();
                }
            }
            catch (Exception ex)
            {
                job.Status = "Failed";
                job.ErrorMessage = $"Python AI servisine ulaşılamadı: {ex.Message}";
                await _context.SaveChangesAsync();
            }

            return Accepted(new { jobId = job.Id, status = job.Status, ticker = job.TickerSymbol });
        }

        // 5. Job Durumu Sorgula
        [HttpGet("jobs/{jobId}")]
        public async Task<IActionResult> GetJobStatus(Guid jobId)
        {
            var job = await _context.AnalysisJobs.FindAsync(jobId);
            if (job == null) return NotFound("İşlem bulunamadı.");
            return Ok(job);
        }

        // 6. Python Webhook Callback (Hem Ara Adımları Hem Nihai Raporu Alır)
        [HttpPost("webhook/callback")]
        public async Task<IActionResult> ReceivePythonCallback([FromBody] PythonWebhookCallbackDto callback)
        {
            var job = await _context.AnalysisJobs.FindAsync(callback.JobId);
            if (job == null) return NotFound("Job bulunamadı.");

           
            if (!string.IsNullOrEmpty(callback.StatusOverride) && callback.FundamentalReport == null)
            {
                job.Status = callback.StatusOverride;
                await _context.SaveChangesAsync();
                return Ok(new { message = "Adım güncellendi." });
            }

            if (callback.IsSuccess)
            {
                job.Status = "Completed";
                job.FundamentalReport = callback.FundamentalReport;
                job.SentimentReport = callback.SentimentReport;
                job.SynthesisReport = callback.SynthesisReport;
                job.SourcesJson = callback.SourcesJson;
                job.CompletedAt = DateTime.UtcNow;
            }
            else
            {
                job.Status = "Failed";
                job.ErrorMessage = callback.ErrorMessage;
                job.CompletedAt = DateTime.UtcNow;
            }

            await _context.SaveChangesAsync();
            return Ok(new { message = "Rapor kaydedildi." });
        }
    }
}
