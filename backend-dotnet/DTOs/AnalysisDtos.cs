namespace FinAgent.Api.DTOs
{
    // Alış işleminde o günkü kur (PurchaseFxRate) da alınır
    public record CreatePortfolioItemDto(string TickerSymbol, decimal Quantity, decimal AverageCost, decimal PurchaseFxRate = 1.0m);

    // Pozisyon Maliyet ve Alış Kuru Elle Düzeltme DTO'su
    public record UpdatePortfolioItemDto(decimal Quantity, decimal AverageCost, decimal PurchaseFxRate);

    // Satış / Pozisyon Azaltma İsteği
    public record SellPortfolioItemDto(decimal QuantityToSell, decimal SalePrice, decimal CurrentFxRate = 1.0m);

    // Analiz başlatırken portföy bağlamı gönderilir
    public record StartAnalyzeContextDto(
        double PortfolioWeightPct,
        double MaxPortfolioWeightPct,
        string LargestPositionTicker,
        double EffectiveN,
        int TotalPositionsCount,
        double PnlPct
    );

    public record TriggerPythonJobRequest(
        Guid JobId,
        string TickerSymbol,
        double PortfolioWeightPct,
        double MaxPortfolioWeightPct,
        string LargestPositionTicker,
        double EffectiveN,
        int TotalPositionsCount,
        decimal Quantity,
        decimal AverageCost,
        double PnlPct
    );

    public record PythonWebhookCallbackDto(
        Guid JobId,
        bool IsSuccess,
        string? FundamentalReport,
        string? SentimentReport,
        string? SynthesisReport,
        string? SourcesJson,
        string? ErrorMessage,
        string? StatusOverride
    );
}
