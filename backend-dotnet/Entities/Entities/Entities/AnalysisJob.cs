namespace FinAgent.Api.Entities
{
    public class AnalysisJob
    {
        public Guid Id { get; set; } = Guid.NewGuid();
        public int PortfolioItemId { get; set; }
        public string TickerSymbol { get; set; } = string.Empty;
        public string Status { get; set; } = "Pending"; 

        // 3 Ajanın Çıktıları:
        public string? FundamentalReport { get; set; } // Ajan 1: Bilanço & Rasyo
        public string? SentimentReport { get; set; }   // Ajan 2: KAP & Haber Akışı
        public string? SynthesisReport { get; set; }   // Ajan 3: Baş Stratejist Sentezi
        
        public string? SourcesJson { get; set; } 
        public string Disclaimer { get; set; } = "SPK mevzuatı uyarınca bu çıktı yapay zeka tarafından kamuya açık verilerle bilgilendirme amaçlı üretilmiştir. Yatırım tavsiyesi değildir.";
        
        public string? ErrorMessage { get; set; }
        public DateTime CreatedAt { get; set; } = DateTime.UtcNow;
        public DateTime? CompletedAt { get; set; }

        public PortfolioItem? PortfolioItem { get; set; }
    }
}
