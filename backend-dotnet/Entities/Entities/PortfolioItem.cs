namespace FinAgent.Api.Entities
{
    public class PortfolioItem
    {
        public int Id { get; set; }
        public string TickerSymbol { get; set; } = string.Empty;
        public decimal Quantity { get; set; }
        public decimal AverageCost { get; set; }
        
        // Alış tarihindeki ağırlıklı ortalama kur (TRY hisseleri için 1.0, USD hisseleri için alış kuru örn: 32.50)
        public decimal AverageFxRate { get; set; } = 1.0m;

        // Satış yapıldıkça biriken Gerçekleşmiş Kâr/Zarar (TRY bazında)
        public decimal RealizedPnlTry { get; set; } = 0.0m;

        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;

        public List<AnalysisJob> AnalysisJobs { get; set; } = new();
    }
}