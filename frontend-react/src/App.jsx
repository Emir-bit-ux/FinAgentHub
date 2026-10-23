import { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import {
  Bot, FileText, TrendingUp, RefreshCw, Upload, AlertTriangle,
  ExternalLink, PlusCircle, Download, CheckCircle2, ShieldAlert,
  Trash2, Clock, Activity, DollarSign, Edit3, Compass, HelpCircle, Globe
} from "lucide-react";
import "./App.css";

const DOTNET_API = "http://localhost:5041/api/PortfolioAnalysis";
const PYTHON_API = "http://localhost:8000/api/agent";
const COLORS = ["#38bdf8", "#4ade80", "#facc15", "#f87171", "#a78bfa", "#fb923c"];

const fmtTR = (val, decimals = 2) => {
  if (val === null || val === undefined || isNaN(val)) return "0,00";
  return Number(val).toLocaleString("tr-TR", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
};

const formatLocalTime = (utcDateStr) => {
  if (!utcDateStr) return "";
  const normalized = utcDateStr.endsWith("Z") || utcDateStr.includes("+") ? utcDateStr : `${utcDateStr}Z`;
  return new Date(normalized).toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};

function App() {
  const [portfolio, setPortfolio] = useState([]);
  const [quotesData, setQuotesData] = useState({ usdTry: 49.57, quotes: {} });
  const [selectedItem, setSelectedItem] = useState(null);
  const [activeJob, setActiveJob] = useState(null);
  const [activeTab, setActiveTab] = useState("synthesis");
  const [isPolling, setIsPolling] = useState(false);
  const [pollingStatusText, setPollingStatusText] = useState("");
  const [analytics, setAnalytics] = useState(null);
  const [hoverPoint, setHoverPoint] = useState(null);

  const [ticker, setTicker] = useState("");
  const [quantity, setQuantity] = useState("");
  const [avgCost, setAvgCost] = useState("");
  const [purchaseFx, setPurchaseFx] = useState("");
  const [fxInputError, setFxInputError] = useState("");

  const [editingItemId, setEditingItemId] = useState(null);
  const [editQty, setEditQty] = useState("");
  const [editCost, setEditCost] = useState("");
  const [editFx, setEditFx] = useState("");

  const [sellingItemId, setSellingItemId] = useState(null);
  const [sellQty, setSellQty] = useState("");
  const [sellPrice, setSellPrice] = useState("");

  const [pdfFile, setPdfFile] = useState(null);
  const [pdfUploading, setPdfUploading] = useState(false);
  const [pdfMessage, setPdfMessage] = useState("");

  const fetchLiveQuotes = async (items) => {
    if (!items || items.length === 0) return;
    try {
      const tickers = items.map((i) => i.tickerSymbol);
      const res = await fetch(`${PYTHON_API}/live-quotes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tickers }),
      });
      if (res.ok) {
        setQuotesData(await res.json());
      }
    } catch (err) {
      console.error("Canlı fiyatlar çekilemedi:", err);
    }
  };

  const fetchMarketAnalytics = async (targetTicker, allItems) => {
    if (!targetTicker) return;
    try {
      const allTickers = (allItems || portfolio).map((x) => x.tickerSymbol);
      const res = await fetch(`${PYTHON_API}/market-analytics`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: targetTicker, portfolioTickers: allTickers }),
      });
      if (res.ok) {
        setAnalytics(await res.json());
      }
    } catch (err) {
      console.error("Analitik çekilemedi:", err);
    }
  };

  const fetchPortfolio = async () => {
    try {
      const res = await fetch(`${DOTNET_API}/portfolio`);
      const data = await res.json();
      setPortfolio(data);
      fetchLiveQuotes(data);

      if (data.length > 0) {
        const current = selectedItem
          ? data.find((x) => x.id === selectedItem.id) || data[0]
          : data[0];
        selectPortfolioItem(current, data);
      }
    } catch (err) {
      console.error("Portföy çekilemedi:", err);
    }
  };

  useEffect(() => {
    fetchPortfolio();
  }, []);

  const selectPortfolioItem = (item, allItems = portfolio) => {
    setSelectedItem(item);
    setPdfMessage("");
    setHoverPoint(null);
    if (item.analysisJobs && item.analysisJobs.length > 0) {
      setActiveJob(item.analysisJobs[0]);
    } else {
      setActiveJob(null);
    }
    fetchMarketAnalytics(item.tickerSymbol, allItems);
  };

  const usdTry = quotesData.usdTry || 49.57;
  const isForeignStock = ticker && !ticker.toUpperCase().trim().endsWith(".IS");

  const handleAddStock = async (e) => {
    e.preventDefault();
    if (!ticker || !quantity || !avgCost) return;

    let cleanT = ticker.toUpperCase().trim();
    try {
      const res = await fetch(`${PYTHON_API}/resolve-ticker/${encodeURIComponent(cleanT)}`);
      if (res.ok) {
        const resolved = await res.json();
        cleanT = resolved.resolvedTicker;
      }
    } catch (err) {
      console.warn("Sembol çözümleyici hatası:", err);
    }

    let fxToUse = 1.0;
    if (!cleanT.endsWith(".IS")) {
      const parsedFx = parseFloat(purchaseFx);
      if (purchaseFx && (parsedFx < 2.0 || parsedFx > usdTry * 1.5)) {
        setFxInputError(`Geçersiz alış kuru (${fmtTR(parsedFx, 2)} ₺). Kur 2,00 ile ${fmtTR(usdTry * 1.5, 2)} ₺ arasında olmalıdır.`);
        return;
      }
      fxToUse = parsedFx || usdTry;
    }

    setFxInputError("");
    await fetch(`${DOTNET_API}/portfolio`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tickerSymbol: cleanT,
        quantity: parseFloat(quantity),
        averageCost: parseFloat(avgCost),
        purchaseFxRate: fxToUse,
      }),
    });

    setTicker("");
    setQuantity("");
    setAvgCost("");
    setPurchaseFx("");
    fetchPortfolio();
  };

  const handleUpdateStock = async (item, e) => {
    e.preventDefault();
    const parsedFx = item.curr === "USD" ? parseFloat(editFx) || usdTry : 1.0;
    if (item.curr === "USD" && (parsedFx < 2.0 || parsedFx > usdTry * 1.5)) {
      alert(`Alış kuru geçerli aralıkta değil (Güncel kur: ${fmtTR(usdTry, 2)} ₺).`);
      return;
    }

    const res = await fetch(`${DOTNET_API}/portfolio/${item.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        quantity: parseFloat(editQty),
        averageCost: parseFloat(editCost),
        purchaseFxRate: parsedFx,
      }),
    });

    if (res.ok) {
      setEditingItemId(null);
      fetchPortfolio();
    }
  };

  const handleSellStock = async (item, e) => {
    e.preventDefault();
    if (!sellQty || !sellPrice) return;
    const currFx = item.curr === "USD" ? usdTry : 1.0;

    const res = await fetch(`${DOTNET_API}/portfolio/${item.id}/sell`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        quantityToSell: parseFloat(sellQty),
        salePrice: parseFloat(sellPrice),
        currentFxRate: currFx,
      }),
    });

    if (res.ok) {
      setSellingItemId(null);
      setSellQty("");
      setSellPrice("");
      fetchPortfolio();
    }
  };

  const handleDeleteStock = async (id, e) => {
    e.stopPropagation();
    await fetch(`${DOTNET_API}/portfolio/${id}`, { method: "DELETE" });
    if (selectedItem?.id === id) setSelectedItem(null);
    fetchPortfolio();
  };

  const handlePdfUpload = async (e) => {
    e.preventDefault();
    if (!pdfFile || !selectedItem) return;

    setPdfUploading(true);
    setPdfMessage("PDF finansal uygunluk ve şirket eşleşmesi açısından doğrulanıyor...");

    const formData = new FormData();
    formData.append("tickerSymbol", selectedItem.tickerSymbol);
    formData.append("file", pdfFile);

    try {
      const res = await fetch(`${PYTHON_API}/upload-pdf`, {
        method: "POST",
        body: formData,
      });
      const data = await res.json();
      if (res.ok) {
        setPdfMessage(`✅ ${data.validationNote} (${data.vectorizedChunks} chunk üretildi)`);
        fetchLiveQuotes(portfolio);
      } else {
        setPdfMessage(`❌ ${data.detail}`);
      }
    } catch (err) {
      setPdfMessage(`❌ Bağlantı hatası: ${err.message}`);
    } finally {
      setPdfUploading(false);
    }
  };

  const handleClearRag = async (tickerSym) => {
    await fetch(`${PYTHON_API}/rag/${encodeURIComponent(tickerSym)}`, { method: "DELETE" });
    setPdfMessage("🗑️ RAG vektör deposu temizlendi.");
    fetchLiveQuotes(portfolio);
  };

  // Çoklu Para Birimi Hesaplamaları
  const enrichedPortfolio = portfolio.map((item, idx) => {
    const q = quotesData.quotes[item.tickerSymbol] || {};
    const curr = q.currency || (item.tickerSymbol.endsWith(".IS") ? "TRY" : "USD");
    const livePrice = q.price || item.averageCost;
    const currentFx = curr === "USD" ? usdTry : 1.0;

    const rawBuyFx = item.averageFxRate || usdTry;
    const isFxValid = curr === "USD" ? rawBuyFx >= 2.0 && rawBuyFx <= usdTry * 1.5 : true;
    const buyFx = curr === "USD" ? (isFxValid ? rawBuyFx : usdTry) : 1.0;

    const marketValNative = item.quantity * livePrice;
    const costValNative = item.quantity * item.averageCost;
    const pnlNative = marketValNative - costValNative;
    const pnlPct = costValNative > 0 ? (pnlNative / costValNative) * 100 : 0;

    const priceEffectTry = (livePrice - item.averageCost) * item.quantity * currentFx;
    const fxEffectTry = costValNative * (currentFx - buyFx);
    const totalItemPnlTry = priceEffectTry + fxEffectTry;

    const marketValTry = marketValNative * currentFx;
    const costValTry = costValNative * buyFx;

    return {
      ...item,
      curr,
      livePrice,
      buyFx,
      currentFx,
      marketValNative,
      pnlNative,
      pnlPct,
      marketValTry,
      costValTry,
      priceEffectTry,
      fxEffectTry,
      totalItemPnlTry,
      isCostAnomaly: Math.abs(pnlPct) > 500,
      beta: q.beta ?? 1.0,
      ragChunks: q.ragChunks || 0,
      ragFileName: q.ragFileName,
      ragWarning: q.ragWarning,
      color: COLORS[idx % COLORS.length],
    };
  });

  const totalPortfolioTry = enrichedPortfolio.reduce((acc, x) => acc + x.marketValTry, 0);
  const totalCostTry = enrichedPortfolio.reduce((acc, x) => acc + x.costValTry, 0);
  const totalPriceEffectTry = enrichedPortfolio.reduce((acc, x) => acc + x.priceEffectTry, 0);
  const totalFxEffectTry = enrichedPortfolio.reduce((acc, x) => acc + x.fxEffectTry, 0);
  const totalRealizedTry = enrichedPortfolio.reduce((acc, x) => acc + (x.realizedPnlTry || 0), 0);
  const totalPnlTry = totalPriceEffectTry + totalFxEffectTry;
  const totalPnlPct = totalCostTry > 0 ? (totalPnlTry / totalCostTry) * 100 : 0;

  // PORTFÖY DÜZEYİ YOĞUNLAŞMA METRİKLERİ (HHI, Efektif Varlık Sayısı N_eff ve En Büyük Pozisyon)
  let hhi = 0;
  let maxWeightPct = 0;
  let largestTicker = "";
  enrichedPortfolio.forEach((x) => {
    const w = totalPortfolioTry > 0 ? x.marketValTry / totalPortfolioTry : 0;
    const wPct = w * 100;
    hhi += w * w;
    if (wPct > maxWeightPct) {
      maxWeightPct = wPct;
      largestTicker = x.tickerSymbol;
    }
  });
  const effectiveN = hhi > 0 ? 1 / hhi : 1;
  const isPortfolioConcentrated = enrichedPortfolio.length >= 2 && maxWeightPct >= 35;

  // PİYASA BAZLI AYRI BETA (BIST 100 vs S&P 500 - Elma ile armutu toplamaz)
  const bistItems = enrichedPortfolio.filter((x) => x.tickerSymbol.endsWith(".IS"));
  const usItems = enrichedPortfolio.filter((x) => !x.tickerSymbol.endsWith(".IS"));
  const bistTotalTry = bistItems.reduce((a, b) => a + b.marketValTry, 0);
  const usTotalTry = usItems.reduce((a, b) => a + b.marketValTry, 0);

  const bistBeta =
    bistTotalTry > 0
      ? bistItems.reduce((acc, x) => acc + x.beta * (x.marketValTry / bistTotalTry), 0)
      : null;
  const usBeta =
    usTotalTry > 0
      ? usItems.reduce((acc, x) => acc + x.beta * (x.marketValTry / usTotalTry), 0)
      : null;

  const handleStartAnalysis = async (item) => {
    setIsPolling(true);
    setPollingStatusText("Paralel ajan orkestrasyonu başlatılıyor...");
    const weightPct = totalPortfolioTry > 0 ? (item.marketValTry / totalPortfolioTry) * 100 : 0;

    try {
      const res = await fetch(`${DOTNET_API}/analyze/${item.id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          portfolioWeightPct: weightPct,
          maxPortfolioWeightPct: maxWeightPct,
          largestPositionTicker: largestTicker,
          effectiveN: effectiveN,
          totalPositionsCount: enrichedPortfolio.length,
          pnlPct: item.pnlPct,
        }),
      });
      const data = await res.json();
      const jobId = data.jobId;

      const interval = setInterval(async () => {
        const jobRes = await fetch(`${DOTNET_API}/jobs/${jobId}`);
        const jobData = await jobRes.json();
        setActiveJob(jobData);
        setPollingStatusText(jobData.status || "Analiz ediliyor...");

        if (jobData.status === "Completed" || jobData.status === "Failed") {
          clearInterval(interval);
          setIsPolling(false);
          fetchPortfolio();
        }
      }, 2000);
    } catch (err) {
      console.error("Analiz başlatılamadı:", err);
      setIsPolling(false);
    }
  };

  const parseStructuredStrategy = (job = activeJob) => {
    if (!job?.synthesisReport) return null;
    try {
      const parsed = JSON.parse(job.synthesisReport);
      return { ...parsed, isLegacy: (parsed.schemaVersion || 1) < 4 };
    } catch {
      return { isLegacyMarkdown: true, isLegacy: true, rawText: job.synthesisReport };
    }
  };

  const parsedSources = () => {
    if (!activeJob?.sourcesJson) return [];
    try {
      return JSON.parse(activeJob.sourcesJson);
    } catch {
      return [];
    }
  };

  const handleDownloadReport = () => {
    if (!activeJob || !selectedItem) return;
    const strat = parseStructuredStrategy();
    const stratText = strat?.isLegacyMarkdown
      ? strat.rawText
      : `**Yönetici Gözlemi:** ${strat?.executiveStance}\n**Formül Güven Skoru:** %${strat?.confidenceScore}\n**Makro Bağlam:** ${strat?.macroContextSummary}\n**Portföy Dağılım Gözlemi:** ${strat?.positionRiskObservation}\n\n**Bilanço & Haber Uyumu:**\n${strat?.alignmentSummary}`;

    const content = `# ${selectedItem.tickerSymbol} — Çok Ajanlı Yatırım İstihbarat Raporu\nTarih: ${formatLocalTime(activeJob.completedAt || activeJob.createdAt)}\n\n## 1. Bilanço, Tablolar & RAG Analizi\n${activeJob.fundamentalReport}\n\n## 2. Resmi Bildirimler (KAP/SEC) & Haber Duyarlılığı\n${activeJob.sentimentReport}\n\n## 3. Baş Stratejist Sentezi\n${stratText}\n\n---\n*${activeJob.disclaimer}*`;

    const blob = new Blob([content], { type: "text/markdown;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${selectedItem.tickerSymbol}_FinAgent_Raporu.md`;
    a.click();
  };

  const strategyData = parseStructuredStrategy();
  const currentEnriched = enrichedPortfolio.find((x) => x.id === selectedItem?.id);
  const currentWeightPct =
    currentEnriched && totalPortfolioTry > 0
      ? (currentEnriched.marketValTry / totalPortfolioTry) * 100
      : 0;

  let cumulativePercent = 0;
  const getCoordinatesForPercent = (percent) => [
    Math.cos(2 * Math.PI * percent),
    Math.sin(2 * Math.PI * percent),
  ];

  return (
    <div className="app-container">
      <header className="header">
        <h1>
          <Bot size={26} /> FinAgent Hub — Çok Ajanlı Portföy & RAG Karar Destek Sistemi
        </h1>
        <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
          <span className="badge">Canlı USD/TRY: {fmtTR(usdTry, 2)} ₺</span>
          {bistBeta !== null && <span className="badge">BIST Beta (XU100): {fmtTR(bistBeta, 2)}</span>}
          {usBeta !== null && <span className="badge">ABD Beta (S&P 500): {fmtTR(usBeta, 2)}</span>}
          <span className="badge">v7.0 Verified RAG & Empirical Beta</span>
        </div>
      </header>

      {/* ÜST ÖZET KARTLARI */}
      <div className="summary-grid">
        <div className="stat-card">
          <span className="stat-label">Toplam Portföy Değeri (TRY Bazlı)</span>
          <span className="stat-value">{fmtTR(totalPortfolioTry, 2)} ₺</span>
          <span className="stat-sub" style={{ color: "#94a3b8" }}>
            ≈ {fmtTR(totalPortfolioTry / usdTry, 2)} USD
          </span>
        </div>

        <div className="stat-card">
          <span className="stat-label">Açık Kâr/Zarar (Fiyat + Kur Ayrımı)</span>
          <span className={`stat-value ${totalPnlTry >= 0 ? "pos" : "neg"}`}>
            {totalPnlTry >= 0 ? "+" : ""}
            {fmtTR(totalPnlTry, 0)} ₺ (%{fmtTR(totalPnlPct, 2)})
          </span>
          <span className="stat-sub" style={{ color: "#cbd5e1", fontSize: "0.75rem" }}>
            Fiyat Etkisi: <b className={totalPriceEffectTry >= 0 ? "pos" : "neg"}>{totalPriceEffectTry >= 0 ? "+" : ""}{fmtTR(totalPriceEffectTry, 0)} ₺</b>{" "}
            | Kur Etkisi: <b className={totalFxEffectTry >= 0 ? "pos" : "neg"}>{totalFxEffectTry >= 0 ? "+" : ""}{fmtTR(totalFxEffectTry, 0)} ₺</b>
          </span>
        </div>

        <div className="stat-card">
          <span className="stat-label">Portföy Dağılım Kalitesi (HHI & N_eff)</span>
          <span className="stat-value" style={{ fontSize: "1.15rem", color: isPortfolioConcentrated ? "#f87171" : "#4ade80" }}>
            {enrichedPortfolio.length < 2
              ? "Tek Varlıklı Portföy"
              : isPortfolioConcentrated
              ? ` Yüksek Yoğunlaşma (${largestTicker} %${fmtTR(maxWeightPct, 1)})`
              : `${enrichedPortfolio.length} Varlık — Dengeli Dağılım`}
          </span>
          <span className="stat-sub" style={{ color: "#94a3b8" }}>
            Efektif Varlık Sayısı (N_eff): <b>{fmtTR(effectiveN, 2)}</b> / {enrichedPortfolio.length} | Gerçekleşmiş K/Z: {fmtTR(totalRealizedTry, 0)} ₺
          </span>
        </div>

        {/* SVG HALKA GRAFİK */}
        <div className="donut-card">
          <svg viewBox="-1 -1 2 2" style={{ width: "76px", height: "76px", transform: "rotate(-90deg)" }}>
            {totalPortfolioTry > 0 &&
              enrichedPortfolio.map((slice) => {
                const pct = slice.marketValTry / totalPortfolioTry;
                const [startX, startY] = getCoordinatesForPercent(cumulativePercent);
                cumulativePercent += pct;
                const [endX, endY] = getCoordinatesForPercent(cumulativePercent);
                const largeArcFlag = pct > 0.5 ? 1 : 0;
                const pathData = `M ${startX} ${startY} A 1 1 0 ${largeArcFlag} 1 ${endX} ${endY} L 0 0`;
                return <path key={slice.id} d={pathData} fill={slice.color} />;
              })}
            <circle cx="0" cy="0" r="0.6" fill="#111827" />
          </svg>
          <div style={{ flex: 1 }}>
            <div className="stat-label" style={{ marginBottom: "4px" }}>Portföy Ağırlık Dağılımı</div>
            {enrichedPortfolio.map((item) => {
              const w = totalPortfolioTry > 0 ? (item.marketValTry / totalPortfolioTry) * 100 : 0;
              return (
                <div key={item.id} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.78rem", marginBottom: "2px" }}>
                  <span style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                    <span style={{ width: "8px", height: "8px", borderRadius: "50%", background: item.color }} />
                    {item.tickerSymbol}
                  </span>
                  <b>%{fmtTR(w, 1)}</b>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="grid-layout">
        {/* SOL PANEL */}
        <div>
          <div className="card">
            <h2><PlusCircle size={18} /> Pozisyon Ekle (Akıllı Sembol & Kur)</h2>
            <form onSubmit={handleAddStock} className="input-group">
              <input
                placeholder="Sembol (Örn: THYAO, KTLEV, AAPL, MU)"
                value={ticker}
                onChange={(e) => setTicker(e.target.value)}
              />
              <div className="input-row">
                <input
                  type="number"
                  step="any"
                  placeholder="Adet (Örn: 100)"
                  value={quantity}
                  onChange={(e) => setQuantity(e.target.value)}
                />
                <input
                  type="number"
                  step="any"
                  placeholder="Birim Maliyet"
                  value={avgCost}
                  onChange={(e) => setAvgCost(e.target.value)}
                />
              </div>
              {isForeignStock && (
                <input
                  type="number"
                  step="any"
                  placeholder={`Alış Günü USD/TRY Kuru (Boşsa: ${fmtTR(usdTry, 2)} ₺)`}
                  value={purchaseFx}
                  onChange={(e) => setPurchaseFx(e.target.value)}
                />
              )}
              {fxInputError && <p style={{ color: "#f87171", fontSize: "0.78rem" }}>{fxInputError}</p>}
              <button type="submit">Portföye Ekle / Maliyet Birleştir</button>
            </form>
          </div>

          <div className="card">
            <h2><TrendingUp size={18} /> Portföy Pozisyonları ({enrichedPortfolio.length})</h2>
            {enrichedPortfolio.map((item) => {
              const weightPct = totalPortfolioTry > 0 ? (item.marketValTry / totalPortfolioTry) * 100 : 0;
              const itemHasConcWarning = enrichedPortfolio.length >= 2 && weightPct >= 35;

              return (
                <div
                  key={item.id}
                  className={`portfolio-item ${selectedItem?.id === item.id ? "active" : ""}`}
                  onClick={() => selectPortfolioItem(item)}
                >
                  <div className="portfolio-item-header">
                    <div>
                      <span className="ticker">{item.tickerSymbol}</span>
                      {itemHasConcWarning && (
                        <span style={{ fontSize: "0.7rem", color: "#facc15", marginLeft: "6px" }}>
                          • Ağırlık %{fmtTR(weightPct, 1)}
                        </span>
                      )}
                    </div>
                    <div style={{ display: "flex", gap: "4px" }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          selectPortfolioItem(item);
                          handleStartAnalysis(item);
                        }}
                        disabled={isPolling}
                      >
                        <RefreshCw size={12} /> Analiz Et
                      </button>
                      <button
                        className="btn-secondary"
                        onClick={(e) => {
                          e.stopPropagation();
                          setEditingItemId(editingItemId === item.id ? null : item.id);
                          setEditQty(item.quantity.toString());
                          setEditCost(item.averageCost.toString());
                          setEditFx(item.buyFx.toFixed(2));
                        }}
                        title="Düzenle"
                      >
                        <Edit3 size={12} />
                      </button>
                      <button
                        className="btn-secondary"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSellingItemId(sellingItemId === item.id ? null : item.id);
                          setSellPrice(item.livePrice.toString());
                        }}
                        title="Satış Yap"
                      >
                        <DollarSign size={12} />
                      </button>
                      <button
                        className="btn-secondary"
                        onClick={(e) => handleDeleteStock(item.id, e)}
                        title="Sil"
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  </div>

                  <div className="metrics-grid">
                    <div>Güncel: <b>{fmtTR(item.livePrice, 2)} {item.curr}</b></div>
                    <div>Maliyet: <b>{fmtTR(item.averageCost, 2)} {item.curr}</b> ({fmtTR(item.quantity, 0)} ad.)</div>
                    <div>Değer: <b>{fmtTR(item.marketValNative, 2)} {item.curr}</b></div>
                    <div className={item.pnlNative >= 0 ? "pos" : "neg"}>
                      K/Z: <b>{item.pnlNative >= 0 ? "+" : ""}{fmtTR(item.pnlNative, 2)} {item.curr} (%{fmtTR(item.pnlPct, 1)})</b>
                    </div>
                  </div>

                  {item.curr === "USD" && (
                    <div style={{ fontSize: "0.73rem", color: "#94a3b8", marginTop: "4px" }}>
                      Alış Kuru: <b>{fmtTR(item.buyFx, 2)} ₺</b> | Fiyat K/Z: {fmtTR(item.priceEffectTry, 0)} ₺ | Kur K/Z: {fmtTR(item.fxEffectTry, 0)} ₺
                    </div>
                  )}

                  {editingItemId === item.id && (
                    <form
                      onClick={(e) => e.stopPropagation()}
                      onSubmit={(e) => handleUpdateStock(item, e)}
                      style={{ marginTop: "10px", paddingTop: "8px", borderTop: "1px dashed #334155" }}
                    >
                      <div className="input-row" style={{ marginBottom: "6px" }}>
                        <input
                          type="number"
                          step="any"
                          placeholder="Adet"
                          value={editQty}
                          onChange={(e) => setEditQty(e.target.value)}
                        />
                        <input
                          type="number"
                          step="any"
                          placeholder="Birim Maliyet"
                          value={editCost}
                          onChange={(e) => setEditCost(e.target.value)}
                        />
                      </div>
                      {item.curr === "USD" && (
                        <input
                          type="number"
                          step="any"
                          placeholder="Alış Günü USD/TRY Kuru"
                          value={editFx}
                          onChange={(e) => setEditFx(e.target.value)}
                          style={{ marginBottom: "6px" }}
                        />
                      )}
                      <button type="submit" style={{ width: "100%" }}>Kaydet</button>
                    </form>
                  )}

                  {sellingItemId === item.id && (
                    <form
                      onClick={(e) => e.stopPropagation()}
                      onSubmit={(e) => handleSellStock(item, e)}
                      style={{ marginTop: "10px", paddingTop: "8px", borderTop: "1px dashed #334155" }}
                    >
                      <div className="input-row" style={{ marginBottom: "6px" }}>
                        <input
                          type="number"
                          step="any"
                          placeholder={`Adet (Max ${item.quantity})`}
                          value={sellQty}
                          onChange={(e) => setSellQty(e.target.value)}
                        />
                        <input
                          type="number"
                          step="any"
                          placeholder="Satış Fiyatı"
                          value={sellPrice}
                          onChange={(e) => setSellPrice(e.target.value)}
                        />
                      </div>
                      <button type="submit" style={{ width: "100%", background: "#16a34a" }}>Satışı Onayla</button>
                    </form>
                  )}

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "8px", fontSize: "0.73rem" }}>
                    <span style={{ color: item.ragChunks >= 3 ? "#4ade80" : "#64748b" }}>
                      {item.ragChunks >= 3
                        ? `Doğrulanmış RAG: ${item.ragChunks} chunk`
                        : " Resmi Tablo + SEC/KAP Modu"}
                    </span>
                    <span style={{ color: "#94a3b8" }}>Portföy Ağırlığı: <b>%{fmtTR(weightPct, 1)}</b></span>
                  </div>

                  <div className="weight-bar-bg">
                    <div className="weight-bar-fill" style={{ width: `${weightPct}%`, background: item.color }} />
                  </div>
                </div>
              );
            })}
          </div>

          {currentEnriched && (
            <div className="card">
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                <h2 style={{ marginBottom: 0 }}><Upload size={18} /> {currentEnriched.tickerSymbol} — Faaliyet Raporu (RAG)</h2>
                {currentEnriched.ragChunks > 0 && (
                  <button className="btn-secondary" onClick={() => handleClearRag(currentEnriched.tickerSymbol)} style={{ padding: "4px 8px", fontSize: "0.72rem" }}>
                    RAG Sil
                  </button>
                )}
              </div>
              <p style={{ fontSize: "0.75rem", color: "#94a3b8", marginBottom: "8px" }}>
                Yalnızca şirketin resmi Faaliyet Raporu / 10-K PDF belgeleri kabul edilir (Kişisel/alakasız PDF'ler otomatik reddedilir).
              </p>
              <form onSubmit={handlePdfUpload} className="input-group">
                <input
                  type="file"
                  accept="application/pdf"
                  onChange={(e) => setPdfFile(e.target.files[0])}
                />
                <button type="submit" disabled={pdfUploading || !pdfFile}>
                  {pdfUploading ? "Doğrulanıyor..." : "Faaliyet Raporu Yükle & Doğrula"}
                </button>
              </form>
              {pdfMessage && (
                <p style={{ marginTop: "8px", fontSize: "0.78rem", color: "#38bdf8" }}>{pdfMessage}</p>
              )}
            </div>
          )}
        </div>

        {/* SAĞ PANEL */}
        <div className="card">
          {!selectedItem ? (
            <p>Analiz görmek için soldan bir hisse seçin.</p>
          ) : (
            <>
              {isPortfolioConcentrated && (
                <div className="alert-banner">
                  <AlertTriangle size={18} />
                  <div>
                    <b>Portföy Yoğunlaşma Uyarısı:</b> Portföyünüzde {enrichedPortfolio.length} varlık bulunmasına rağmen toplam değerin{" "}
                    <b>%{fmtTR(maxWeightPct, 1)}</b>'i tek başına <b>{largestTicker}</b> pozisyonundadır (Efektif Varlık Sayısı N_eff: <b>{fmtTR(effectiveN, 2)}</b>).
                    Seçili {selectedItem.tickerSymbol} hissesinin ağırlığı ise <b>%{fmtTR(currentWeightPct, 1)}</b>'dir.
                  </div>
                </div>
              )}

              {analytics && analytics.series && analytics.series.length > 1 && (
                <div className="chart-panel">
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px", flexWrap: "wrap", gap: "8px" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "14px", fontSize: "0.85rem" }}>
                      <span style={{ fontWeight: 700, display: "flex", alignItems: "center", gap: "6px" }}>
                        <Activity size={16} color="#38bdf8" /> 6 Aylık Normalize Performans (Baz=100)
                      </span>
                      <span style={{ display: "flex", alignItems: "center", gap: "5px", color: "#38bdf8" }}>
                        <span style={{ width: "14px", height: "3px", background: "#38bdf8", display: "inline-block" }} />
                        {selectedItem.tickerSymbol} ({analytics.stockReturn6mPct >= 0 ? "+" : ""}%{fmtTR(analytics.stockReturn6mPct, 1)})
                      </span>
                      <span style={{ display: "flex", alignItems: "center", gap: "5px", color: "#94a3b8" }}>
                        <span style={{ width: "14px", height: "2px", borderBottom: "2px dashed #94a3b8", display: "inline-block" }} />
                        {analytics.benchmarkName} ({analytics.benchReturn6mPct >= 0 ? "+" : ""}%{fmtTR(analytics.benchReturn6mPct, 1)})
                      </span>
                    </div>

                    <div style={{ display: "flex", gap: "12px", fontSize: "0.78rem", color: "#cbd5e1" }}>
                      <span>Yıllık Volatilite: <b>%{fmtTR(analytics.volatilityPct, 1)}</b></span>
                      <span>Gerçek Beta ({analytics.benchmarkName}): <b>{fmtTR(analytics.beta, 2)}</b></span>
                      {Object.keys(analytics.correlations || {}).map((k) => (
                        <span key={k}>Korelasyon ({k}): <b>{fmtTR(analytics.correlations[k], 2)}</b></span>
                      ))}
                    </div>
                  </div>

                  <div style={{ fontSize: "0.76rem", color: "#94a3b8", marginBottom: "6px", minHeight: "18px" }}>
                    {hoverPoint ? (
                      <span>
                        <b>{hoverPoint.date}</b> — {selectedItem.tickerSymbol} Fiyat: <b>{fmtTR(hoverPoint.price, 2)} {currentEnriched?.curr}</b> (Endeks: <b>{fmtTR(hoverPoint.stockNorm, 1)}</b>) | {analytics.benchmarkName}: <b>{fmtTR(hoverPoint.benchNorm, 1)}</b>
                      </span>
                    ) : (
                      <span>Grafik detaylarını görmek için fareyi çizgi üzerinde gezdirin.</span>
                    )}
                  </div>

                  {(() => {
                    const pts = analytics.series;
                    const allVals = pts.flatMap((p) => [p.stockNorm, p.benchNorm]);
                    const minV = Math.floor(Math.min(...allVals) * 0.98);
                    const maxV = Math.ceil(Math.max(...allVals) * 1.02);
                    const range = maxV - minV || 1;
                    const w = 720;
                    const h = 120;
                    const padL = 36;
                    const padB = 20;
                    const plotW = w - padL - 10;
                    const plotH = h - padB - 10;

                    const toPoints = (key) =>
                      pts
                        .map((p, i) => {
                          const x = padL + (i / (pts.length - 1)) * plotW;
                          const y = 5 + plotH - ((p[key] - minV) / range) * plotH;
                          return `${x.toFixed(1)},${y.toFixed(1)}`;
                        })
                        .join(" ");

                    return (
                      <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: "130px", overflow: "visible" }}>
                        <text x="2" y="14" fill="#64748b" fontSize="10">{maxV}</text>
                        <text x="2" y={5 + plotH / 2} fill="#64748b" fontSize="10">{Math.round((maxV + minV) / 2)}</text>
                        <text x="2" y={5 + plotH} fill="#64748b" fontSize="10">{minV}</text>
                        <line x1={padL} y1={5 + plotH / 2} x2={w - 10} y2={5 + plotH / 2} stroke="#1e293b" strokeWidth="1" />
                        <polyline fill="none" stroke="#64748b" strokeWidth="1.8" strokeDasharray="4 4" points={toPoints("benchNorm")} />
                        <polyline fill="none" stroke="#38bdf8" strokeWidth="2.5" points={toPoints("stockNorm")} />
                        {pts.map((p, i) => {
                          const x = padL + (i / (pts.length - 1)) * plotW;
                          const y = 5 + plotH - ((p.stockNorm - minV) / range) * plotH;
                          const showDate = i === 0 || i === Math.floor(pts.length / 2) || i === pts.length - 1;
                          return (
                            <g key={i}>
                              {showDate && (
                                <text x={x - 14} y={h - 2} fill="#64748b" fontSize="10">
                                  {p.shortDate}
                                </text>
                              )}
                              <circle
                                cx={x}
                                cy={y}
                                r="5"
                                fill="transparent"
                                style={{ cursor: "pointer" }}
                                onMouseEnter={() => setHoverPoint(p)}
                              />
                            </g>
                          );
                        })}
                      </svg>
                    );
                  })()}
                </div>
              )}

              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "14px", flexWrap: "wrap", gap: "10px" }}>
                <h2><FileText size={20} /> {selectedItem.tickerSymbol} — Çoklu Ajan İstihbarat Raporu</h2>

                <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                  {selectedItem.analysisJobs && selectedItem.analysisJobs.length > 0 && (
                    <select
                      value={activeJob?.id || ""}
                      onChange={(e) => {
                        const found = selectedItem.analysisJobs.find((j) => j.id === e.target.value);
                        if (found) setActiveJob(found);
                      }}
                    >
                      {selectedItem.analysisJobs.map((j, i) => {
                        const st = parseStructuredStrategy(j);
                        const vTag = st?.isLegacy ? "[Eski Sürüm]" : "[v7.0 Doğrulanmış]";
                        return (
                          <option key={j.id} value={j.id}>
                            {vTag} Rapor #{selectedItem.analysisJobs.length - i} — {formatLocalTime(j.completedAt || j.createdAt)}
                          </option>
                        );
                      })}
                    </select>
                  )}

                  {activeJob && activeJob.status === "Completed" && (
                    <>
                      <span className="badge">
                        <Clock size={12} style={{ display: "inline", marginRight: "4px" }} />
                        {formatLocalTime(activeJob.completedAt || activeJob.createdAt)}
                        {strategyData?.analysisDurationSec ? ` (${fmtTR(strategyData.analysisDurationSec, 1)} sn)` : ""}
                      </span>
                      <button className="btn-secondary" onClick={handleDownloadReport}>
                        <Download size={14} /> .MD İndir
                      </button>
                    </>
                  )}
                </div>
              </div>

              {isPolling && (
                <div className="report-box" style={{ padding: "28px" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "10px" }}>
                    <RefreshCw size={24} style={{ color: "#38bdf8" }} />
                    <h3>{pollingStatusText}</h3>
                  </div>
                  <p style={{ color: "#94a3b8", fontSize: "0.86rem" }}>
                    Tablo tutarlılığı denetleniyor, uydurma atıflar filtreleniyor ve formül bazlı güven skoru hesaplanıyor...
                  </p>
                </div>
              )}

              {!isPolling && activeJob && activeJob.status === "Completed" && (
                <>
                  {strategyData?.isLegacy && (
                    <div className="alert-banner" style={{ background: "rgba(250, 204, 21, 0.1)", borderColor: "rgba(250, 204, 21, 0.4)", color: "#fde047" }}>
                       Bu rapor eski sürümde üretilmiştir. Doğrulanmış atıflar, formül bazlı güven skoru ve tutarlılık kontrolü için sol karttan <b>"Analiz Et"</b> butonuna basın.
                    </div>
                  )}

                  <div className="tabs">
                    <button
                      className={`tab-btn ${activeTab === "fundamental" ? "active" : ""}`}
                      onClick={() => setActiveTab("fundamental")}
                    >
                       1. Ajan: Bilanço, Tablolar & Tutarlılık
                    </button>
                    <button
                      className={`tab-btn ${activeTab === "sentiment" ? "active" : ""}`}
                      onClick={() => setActiveTab("sentiment")}
                    >
                       2. Ajan: SEC EDGAR / KAP & Insider
                    </button>
                    <button
                      className={`tab-btn ${activeTab === "synthesis" ? "active" : ""}`}
                      onClick={() => setActiveTab("synthesis")}
                    >
                       3. Ajan: Baş Stratejist & Makro Sentez
                    </button>
                  </div>

                  {activeTab === "fundamental" && (
                    <div className="report-box">
                      <ReactMarkdown>{activeJob.fundamentalReport}</ReactMarkdown>
                    </div>
                  )}

                  {activeTab === "sentiment" && (
                    <div className="report-box">
                      <ReactMarkdown>{activeJob.sentimentReport}</ReactMarkdown>
                    </div>
                  )}

                  {activeTab === "synthesis" && strategyData && (
                    <div>
                      {strategyData.isLegacyMarkdown ? (
                        <div className="report-box">
                          <ReactMarkdown>{strategyData.rawText}</ReactMarkdown>
                        </div>
                      ) : (
                        <>
                          <div className="strategy-top-grid">
                            <div className="strategy-mini-card">
                              <div className="stat-label">Analitik Gözlem Duruşu</div>
                              <div style={{ fontSize: "1.02rem", fontWeight: 700, color: "#38bdf8" }}>
                                {strategyData.executiveStance}
                              </div>
                            </div>
                            <div className="strategy-mini-card">
                              <div className="stat-label">Deterministik Güven & Sentiment</div>
                              <div style={{ fontSize: "1.05rem", fontWeight: 700, color: strategyData.confidenceScore >= 70 ? "#4ade80" : "#facc15" }}>
                                Güven: %{strategyData.confidenceScore} | Sentiment: {strategyData.sentimentScore > 0 ? `+${strategyData.sentimentScore}` : strategyData.sentimentScore}
                              </div>
                            </div>
                            <div className="strategy-mini-card">
                              <div className="stat-label">Veri Kalitesi & Tutarlılık Denetimi</div>
                              <div style={{ fontSize: "0.76rem", color: strategyData.consistencyFlags?.length ? "#fde047" : "#cbd5e1" }}>
                                {strategyData.dataQualityNote}
                              </div>
                            </div>
                          </div>

                          {strategyData.macroContextSummary && (
                            <div className="report-box" style={{ marginBottom: "14px", borderLeft: "4px solid #38bdf8" }}>
                              <h3 style={{ marginTop: 0, display: "flex", alignItems: "center", gap: "6px" }}>
                                <Globe size={17} /> Makroekonomik Bağlam (Tarihli & Rakamlı Göstergeler)
                              </h3>
                              <p style={{ marginBottom: 0 }}>{strategyData.macroContextSummary}</p>
                            </div>
                          )}

                          {(strategyData.positionRiskObservation || strategyData.positionSpecificAdvice) && (
                            <div className="report-box" style={{ marginBottom: "14px", borderLeft: "4px solid #facc15" }}>
                              <h3 style={{ marginTop: 0 }}>
                                 Portföy Dağılım & Pozisyon Gözlemi (Seçili: %{fmtTR(currentWeightPct, 1)} | Max: {largestTicker} %{fmtTR(maxWeightPct, 1)})
                              </h3>
                              <p style={{ marginBottom: 0 }}>
                                {strategyData.positionRiskObservation || strategyData.positionSpecificAdvice}
                              </p>
                            </div>
                          )}

                          <div className="report-box" style={{ marginBottom: "14px" }}>
                            <h3 style={{ marginTop: 0 }}>Bilanço, Tutarlılık ve Resmi Bildirimler (SEC/KAP) Uyumu</h3>
                            <p style={{ marginBottom: 0 }}>{strategyData.alignmentSummary}</p>
                          </div>

                          <div className="strategy-columns">
                            <div className="report-box">
                              <h3 style={{ color: "#4ade80", marginTop: 0, display: "flex", alignItems: "center", gap: "6px" }}>
                                <CheckCircle2 size={18} /> Mevcut Güçlü Yönler (Bilanço & FCF)
                              </h3>
                              {(strategyData.currentStrengths || strategyData.bullishFactors)?.map((bf, i) => (
                                <div key={i} className="point-card bull">
                                  <b>{bf.title}</b>
                                  <p style={{ fontSize: "0.84rem", color: "#cbd5e1", marginTop: "4px", marginBottom: 0 }}>
                                    {bf.detail}
                                  </p>
                                </div>
                              ))}
                            </div>

                            <div className="report-box">
                              <h3 style={{ color: "#38bdf8", marginTop: 0, display: "flex", alignItems: "center", gap: "6px" }}>
                                <Compass size={18} /> İleriye Dönük Katalizörler (20.10.2026 Sonrası)
                              </h3>
                              {strategyData.forwardCatalysts?.map((fc, i) => (
                                <div key={i} className="point-card">
                                  <b>{fc.title}</b>
                                  <p style={{ fontSize: "0.84rem", color: "#cbd5e1", marginTop: "4px", marginBottom: 0 }}>
                                    {fc.detail}
                                  </p>
                                </div>
                              ))}
                            </div>
                          </div>

                          <div className="strategy-columns" style={{ marginTop: "14px" }}>
                            <div className="report-box">
                              <h3 style={{ color: "#f87171", marginTop: 0, display: "flex", alignItems: "center", gap: "6px" }}>
                                <ShieldAlert size={18} /> En Kritik Temel & Portföy Riskleri
                              </h3>
                              {strategyData.keyRisks?.map((kr, i) => (
                                <div key={i} className="point-card risk">
                                  <b>{kr.title}</b>
                                  <p style={{ fontSize: "0.84rem", color: "#cbd5e1", marginTop: "4px", marginBottom: 0 }}>
                                    {kr.detail}
                                  </p>
                                </div>
                              ))}
                            </div>

                            <div className="report-box">
                              <h3 style={{ color: "#a78bfa", marginTop: 0, display: "flex", alignItems: "center", gap: "6px" }}>
                                <HelpCircle size={18} /> Görüşü Ne Değiştirir? (Tezi Bozan Koşullar)
                              </h3>
                              {strategyData.whatChangesTheView?.map((wc, i) => (
                                <div key={i} className="point-card" style={{ borderLeftColor: "#a78bfa" }}>
                                  <b>{wc.title}</b>
                                  <p style={{ fontSize: "0.84rem", color: "#cbd5e1", marginTop: "4px", marginBottom: 0 }}>
                                    {wc.detail}
                                  </p>
                                </div>
                              ))}
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                  )}

                  <div style={{ marginTop: "16px" }}>
                    <h4 style={{ fontSize: "0.8rem", color: "#94a3b8" }}>Doğrulanmış Resmi Bildirimler ve Ağırlıklı Kaynaklar:</h4>
                    <div className="sources-list">
                      {parsedSources().map((s, idx) => (
                        <a
                          key={idx}
                          href={s.url?.startsWith("http") ? s.url : "#"}
                          target="_blank"
                          rel="noreferrer"
                          className="source-tag"
                        >
                          <b>{s.refId || `[${idx + 1}]`}</b> [{s.type}] {s.name}{" "}
                          {s.weight ? `(Ağırlık: ${fmtTR(s.weight, 2)})` : ""}{" "}
                          {s.url?.startsWith("http") && <ExternalLink size={11} style={{ display: "inline" }} />}
                        </a>
                      ))}
                    </div>
                  </div>

                  <div className="disclaimer">
                    <AlertTriangle size={14} style={{ display: "inline", marginRight: "6px" }} />
                    {activeJob.disclaimer}
                  </div>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
