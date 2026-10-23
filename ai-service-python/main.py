import os
import re
import time
import json
import shutil
import asyncio
import httpx
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from urllib.parse import urlparse
from fastapi import FastAPI, BackgroundTasks, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from google import genai
from google.genai import types
from rag_engine import ingest_pdf_to_vector_store, search_company_documents, get_rag_status, clear_rag_store

load_dotenv()

app = FastAPI(title="FinAgent Quant & Verified Multi-Agent Service", version="7.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SERPER_API_KEY = os.getenv("SERPER_API_KEY")
DOTNET_WEBHOOK_URL = os.getenv("DOTNET_WEBHOOK_URL", "http://localhost:5041/api/PortfolioAnalysis/webhook/callback")

UPLOAD_DIR = "uploaded_pdfs"
os.makedirs(UPLOAD_DIR, exist_ok=True)

_CACHE = {}

def get_cached(key: str, ttl_seconds: int):
    if key in _CACHE:
        val, ts = _CACHE[key]
        if time.time() - ts < ttl_seconds:
            return val
    return None

def set_cached(key: str, val):
    _CACHE[key] = (val, time.time())


class AnalyzeRequest(BaseModel):
    jobId: str
    tickerSymbol: str
    portfolioWeightPct: float = 0.0
    maxPortfolioWeightPct: float = 0.0
    largestPositionTicker: str = ""
    effectiveN: float = 1.0
    totalPositionsCount: int = 1
    quantity: float = 0.0
    averageCost: float = 0.0
    pnlPct: float = 0.0

class QuotesRequest(BaseModel):
    tickers: list[str]

class ChartRequest(BaseModel):
    ticker: str
    portfolioTickers: list[str] = []

class StrategyPoint(BaseModel):
    title: str = Field(description="Kısa başlık")
    detail: str = Field(description="Nötr analist gözlemi ve SADECE kaynak listesinde var olan geçerli dipnot atfı ([1], [2] vb.)")

class StructuredStrategyOutput(BaseModel):
    executiveStance: str = Field(description="Kısa kurumsal gözlem başlığı")
    sentimentScore: int = Field(description="-100 ile +100 arası ağırlıklı haber duyarlılık skoru")
    macroContextSummary: str = Field(description="Varlığın piyasasına özgü, yalnızca macroEnvironment içindeki canlı göstergelere dayanan tarihli makro gözlem")
    positionRiskObservation: str = Field(description="Portföy yoğunlaşmasını matematiksel dağılım verileriyle açıklayan nötr gözlem; mevzuat veya SPK eşiği iddiası içermez")
    alignmentSummary: str = Field(description="Bilanço rakamları, tutarlılık uyarıları ve resmi KAP/SEC bildirimleri arasındaki uyum")
    currentStrengths: list[StrategyPoint] = Field(description="Mevcut Güçlü Yönler (Kanıtlanmış bilanço ve nakit akışı metrikleri - En fazla 3 madde)")
    forwardCatalysts: list[StrategyPoint] = Field(description="İleriye Dönük Katalizörler (SADECE bugünden [20.10.2026] sonraki ileri tarihli beklentiler; geçmiş olayları buraya yazma - En fazla 3 madde)")
    keyRisks: list[StrategyPoint] = Field(description="En Kritik 3 Temel, Sektörel ve Portföy Dağılım Riski")
    whatChangesTheView: list[StrategyPoint] = Field(description="Görüşü Ne Değiştirir? (Mevcut analitik görünümü değiştirecek 2-3 somut finansal/operasyonel eşik)")

# ==========================================================
# 1. TÜRKÇE SAYI BİÇİMLENDİRİCİ
# ==========================================================

def tr_num(val: float | None, decimals: int = 2) -> str:
    """Tüm sayıları Türkçe standardında (16.970,92) biçimlendirir."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "Bildirilmedi"
    s = f"{float(val):,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")

def fmt_money(val: float | None, currency: str) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "Bildirilmedi"
    abs_val = abs(float(val))
    sign = "-" if float(val) < 0 else ""
    if abs_val >= 1e12:
        s = tr_num(abs_val / 1e12, 2) + " Trilyon"
    elif abs_val >= 1e9:
        s = tr_num(abs_val / 1e9, 2) + " Milyar"
    elif abs_val >= 1e6:
        s = tr_num(abs_val / 1e6, 2) + " Milyon"
    else:
        s = tr_num(abs_val, 2)
    return f"{sign}{s} {currency}"

def fmt_pct(val: float | None) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "Bildirilmedi"
    return f"%{tr_num(float(val) * 100.0, 2)}"

def fmt_ratio(val: float | None, suffix: str = "x") -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "Hesaplanamadı"
    return f"{tr_num(float(val), 2)}{suffix}"

def verify_citations_and_percentages(text: str, valid_ref_ids: set[str], known_percentages: dict[str, str]) -> str:
    """
    Kaynak listesinde olmayan köşeli parantez atıflarını temizler ve bilinen
    yüzdelerde 100 katlık biçimlendirme hatalarını düzeltir.
    """
    if not text:
        return ""

    def filter_bracket(match):
        tag = match.group(0)
        if tag in valid_ref_ids:
            return tag
        inner = match.group(1)
        parts = [f"[{p.strip()}]" for p in inner.split(",") if f"[{p.strip()}]" in valid_ref_ids]
        return ", ".join(parts)

    cleaned = re.sub(r"\[([^\[\]]+)\]", filter_bracket, text)
    for wrong_pct, correct_pct in known_percentages.items():
        if wrong_pct in cleaned and correct_pct not in cleaned:
            cleaned = cleaned.replace(wrong_pct, correct_pct)
    cleaned = re.sub(r"\s+([.,;:])", r"\1", cleaned)
    return cleaned.strip()

# ==========================================================
# 2. GERÇEK BETA, MAKRO & TUTARLILIK KONTROLLÜ FİNANS MOTORU
# ==========================================================

def get_fx_rate(from_curr: str, to_curr: str) -> float:
    if not from_curr or not to_curr or from_curr == to_curr:
        return 1.0
    cache_key = f"fx_{from_curr}_{to_curr}"
    cached = get_cached(cache_key, 600)
    if cached:
        return cached
    try:
        fx = yf.Ticker(f"{from_curr}{to_curr}=X")
        rate = fx.fast_info.get("lastPrice") or fx.info.get("regularMarketPrice")
        if not rate:
            hist = fx.history(period="5d")
            if not hist.empty:
                rate = float(hist["Close"].iloc[-1])
        val = float(rate) if rate else 1.0
        set_cached(cache_key, val)
        return val
    except Exception:
        return 1.0

def compute_empirical_beta(ticker: str) -> tuple[float, str]:
    """
    yfinance info['beta'] BIST'te hatalı (-0.02 vb.) döndüğü için,
    son 6 aylık ortak işlem günlerinde (inner join) hisse ve yerel endeks (XU100.IS / ^GSPC)
    günlük getirilerinden gerçek Beta'yı hesaplar.
    """
    cache_key = f"beta_{ticker}"
    cached = get_cached(cache_key, 3600)
    if cached:
        return cached

    is_bist = ticker.endswith(".IS")
    bench = "XU100.IS" if is_bist else "^GSPC"
    bench_label = "BIST 100" if is_bist else "S&P 500"

    try:
        s_hist = yf.Ticker(ticker).history(period="6mo")["Close"]
        b_hist = yf.Ticker(bench).history(period="6mo")["Close"]

        s_ret = s_hist.pct_change().dropna()
        b_ret = b_hist.pct_change().dropna()
        s_ret.index = s_ret.index.tz_localize(None).normalize()
        b_ret.index = b_ret.index.tz_localize(None).normalize()

        df = pd.DataFrame({"s": s_ret, "b": b_ret}).dropna()
        if len(df) > 20:
            cov = float(np.cov(df["s"], df["b"])[0, 1])
            var = float(np.var(df["b"]))
            if var > 0:
                beta_val = round(cov / var, 2)
                set_cached(cache_key, (beta_val, bench_label))
                return (beta_val, bench_label)
    except Exception:
        pass

    return (1.0, bench_label)

def get_macro_indicators(ticker: str) -> dict:
    """Varlığın işlem gördüğü piyasaya göre yalnızca doğrulanabilir canlı göstergeleri döndürür."""
    is_bist = ticker.endswith(".IS")
    cache_key = f"macro_v8_{'BIST' if is_bist else 'US'}"
    cached = get_cached(cache_key, 1800)
    if cached:
        return cached

    today_str = datetime.now().strftime("%d.%m.%Y")

    if is_bist:
        usd_try = get_fx_rate("USD", "TRY")
        usd_try_1m_chg = 0.0
        bist100_lvl = 0.0
        bist100_1m_chg = 0.0
        try:
            fx_hist = yf.Ticker("USDTRY=X").history(period="1mo")["Close"]
            if len(fx_hist) > 2:
                usd_try_1m_chg = ((float(fx_hist.iloc[-1]) / float(fx_hist.iloc[0])) - 1.0) * 100.0
            xu_hist = yf.Ticker("XU100.IS").history(period="1mo")["Close"]
            if len(xu_hist) > 2:
                bist100_lvl = float(xu_hist.iloc[-1])
                bist100_1m_chg = ((bist100_lvl / float(xu_hist.iloc[0])) - 1.0) * 100.0
        except Exception:
            pass

        macro = {
            "Piyasa": "Borsa İstanbul (BIST)",
            "Veri Tarihi": today_str,
            "BIST 100 Endeksi (XU100.IS)": f"{tr_num(bist100_lvl, 0)} puan (1 Aylık Değişim: %{tr_num(bist100_1m_chg, 2)})",
            "USD/TRY Kuru (USDTRY=X)": f"{tr_num(usd_try, 2)} ₺ (1 Aylık Değişim: %{tr_num(usd_try_1m_chg, 2)})"
        }
    else:
        us10y = 4.20
        vix = 18.5
        sp500_lvl = 0.0
        sp500_1m_chg = 0.0
        try:
            tnx_hist = yf.Ticker("^TNX").history(period="5d")["Close"]
            if not tnx_hist.empty:
                raw_tnx = float(tnx_hist.iloc[-1])
                us10y = round(raw_tnx / 10.0 if raw_tnx > 15.0 else raw_tnx, 2)
            vix_hist = yf.Ticker("^VIX").history(period="5d")["Close"]
            if not vix_hist.empty:
                vix = round(float(vix_hist.iloc[-1]), 2)
            sp_hist = yf.Ticker("^GSPC").history(period="1mo")["Close"]
            if len(sp_hist) > 2:
                sp500_lvl = float(sp_hist.iloc[-1])
                sp500_1m_chg = ((sp500_lvl / float(sp_hist.iloc[0])) - 1.0) * 100.0
        except Exception:
            pass

        macro = {
            "Piyasa": "ABD Borsaları (NYSE / NASDAQ)",
            "Veri Tarihi": today_str,
            "S&P 500 Endeksi (^GSPC)": f"{tr_num(sp500_lvl, 0)} puan (1 Aylık Değişim: %{tr_num(sp500_1m_chg, 2)})",
            "ABD 10 Yıllık Hazine Tahvil Getirisi (^TNX)": f"%{tr_num(us10y, 2)}",
            "CBOE Volatilite Endeksi (^VIX)": f"{tr_num(vix, 2)}"
        }

    set_cached(cache_key, macro)
    return macro

def fetch_and_compute_deterministic_metrics(ticker: str) -> dict:
    cache_key = f"metrics_v7_{ticker}"
    cached = get_cached(cache_key, 3600)
    if cached:
        return cached

    stock = yf.Ticker(ticker)
    info = stock.info or {}
    now_dt = datetime.now()

    price_curr = info.get("currency", "TRY" if ticker.endswith(".IS") else "USD")
    fin_curr = info.get("financialCurrency") or price_curr
    fx_fin_to_price = get_fx_rate(fin_curr, price_curr)
    usd_try_rate = get_fx_rate("USD", "TRY")

    price = info.get("currentPrice") or info.get("regularMarketPrice")
    market_cap = info.get("marketCap")
    book_value_raw = info.get("bookValue")

    # 1. Resmi Tabloları (income_stmt, balance_sheet, cashflow) Öncelikli Oku (Tutarlılık İçin)
    statements = {}
    stmt_rev = None
    stmt_op_inc = None
    stmt_net_inc = None
    stmt_ebitda = None
    stmt_debt = None
    stmt_cash = None
    stmt_ocf = None

    try:
        inc = stock.income_stmt
        if inc is not None and not inc.empty:
            col = inc.columns[0]
            statements["Son Yıllık/Dönem Tablo Tarihi"] = str(col)[:10]
            if "Total Revenue" in inc.index and pd.notna(inc.loc["Total Revenue", col]):
                stmt_rev = float(inc.loc["Total Revenue", col])
                statements["Toplam Hasılat (Tablo)"] = fmt_money(stmt_rev, fin_curr)
            if "Gross Profit" in inc.index and pd.notna(inc.loc["Gross Profit", col]):
                statements["Brüt Kâr (Tablo)"] = fmt_money(float(inc.loc["Gross Profit", col]), fin_curr)
            if "Operating Income" in inc.index and pd.notna(inc.loc["Operating Income", col]):
                stmt_op_inc = float(inc.loc["Operating Income", col])
                statements["Faaliyet Kârı / EBIT (Tablo)"] = fmt_money(stmt_op_inc, fin_curr)
            if "EBITDA" in inc.index and pd.notna(inc.loc["EBITDA", col]):
                stmt_ebitda = float(inc.loc["EBITDA", col])
                statements["FAVÖK / EBITDA (Tablo)"] = fmt_money(stmt_ebitda, fin_curr)
            if "Net Income" in inc.index and pd.notna(inc.loc["Net Income", col]):
                stmt_net_inc = float(inc.loc["Net Income", col])
                statements["Net Dönem Kârı (Tablo)"] = fmt_money(stmt_net_inc, fin_curr)
    except Exception:
        pass

    try:
        bs = stock.balance_sheet
        if bs is not None and not bs.empty:
            col = bs.columns[0]
            if "Total Assets" in bs.index and pd.notna(bs.loc["Total Assets", col]):
                statements["Toplam Varlıklar"] = fmt_money(float(bs.loc["Total Assets", col]), fin_curr)
            if "Stockholders Equity" in bs.index and pd.notna(bs.loc["Stockholders Equity", col]):
                statements["Toplam Özsermaye"] = fmt_money(float(bs.loc["Stockholders Equity", col]), fin_curr)
            if "Total Debt" in bs.index and pd.notna(bs.loc["Total Debt", col]):
                stmt_debt = float(bs.loc["Total Debt", col])
                statements["Toplam Finansal Borç (Tablo)"] = fmt_money(stmt_debt, fin_curr)
            if "Cash And Cash Equivalents" in bs.index and pd.notna(bs.loc["Cash And Cash Equivalents", col]):
                stmt_cash = float(bs.loc["Cash And Cash Equivalents", col])
                statements["Nakit ve Nakit Benzerleri (Tablo)"] = fmt_money(stmt_cash, fin_curr)
    except Exception:
        pass

    try:
        cf = stock.cashflow
        if cf is not None and not cf.empty:
            col = cf.columns[0]
            if "Operating Cash Flow" in cf.index and pd.notna(cf.loc["Operating Cash Flow", col]):
                stmt_ocf = float(cf.loc["Operating Cash Flow", col])
                statements["İşletme Nakit Akışı (Tablo)"] = fmt_money(stmt_ocf, fin_curr)
            if "Free Cash Flow" in cf.index and pd.notna(cf.loc["Free Cash Flow", col]):
                statements["Serbest Nakit Akışı (FCF)"] = fmt_money(float(cf.loc["Free Cash Flow", col]), fin_curr)
            if "Repurchase Of Capital Stock" in cf.index and pd.notna(cf.loc["Repurchase Of Capital Stock", col]):
                statements["Hisse Geri Alımları (Buybacks)"] = fmt_money(float(cf.loc["Repurchase Of Capital Stock", col]), fin_curr)
    except Exception:
        pass

    # Tablo verisi varsa onu baz al, yoksa info fallback kullan
    total_revenue_raw = stmt_rev if stmt_rev is not None else info.get("totalRevenue")
    total_debt_raw = stmt_debt if stmt_debt is not None else info.get("totalDebt")
    total_cash_raw = stmt_cash if stmt_cash is not None else info.get("totalCash")
    ebitda_raw = stmt_ebitda if stmt_ebitda is not None else info.get("ebitda")

    # Marjları aynı tablodan tutarlı hesapla (TTM vs Çeyreklik çelişkisini önler)
    if stmt_rev and stmt_rev > 0 and stmt_op_inc is not None and stmt_net_inc is not None:
        op_margin = stmt_op_inc / stmt_rev
        net_margin = stmt_net_inc / stmt_rev
    else:
        op_margin = info.get("operatingMargins")
        net_margin = info.get("profitMargins")

    gross_margin = info.get("grossMargins")

    # 2. Kural Tabanlı Tutarlılık Kontrolleri (Consistency Flags)
    consistency_flags = []
    if op_margin is not None and net_margin is not None:
        if op_margin < 0 and net_margin > 0.05:
            consistency_flags.append(
                f"Marj Uyumsuzluğu: Faaliyet marjı ({fmt_pct(op_margin)}) negatifken Net Kâr Marjı ({fmt_pct(net_margin)}) pozitiftir (Yatırım/ertelenmiş vergi geliri veya yfinance TTM/çeyreklik dönem farkı olabilir)."
            )

    net_debt_raw = (total_debt_raw - total_cash_raw) if (total_debt_raw is not None and total_cash_raw is not None) else None
    net_debt_to_ebitda = (net_debt_raw / ebitda_raw) if (net_debt_raw is not None and ebitda_raw and ebitda_raw > 0) else None

    if net_debt_to_ebitda and net_debt_to_ebitda > 4.5 and stmt_ocf and ebitda_raw and stmt_ocf > ebitda_raw * 1.4:
        consistency_flags.append(
            f"FAVÖK Tanım Uyarısı: yfinance FAVÖK verisi ({fmt_money(ebitda_raw, fin_curr)}), İşletme Nakit Akışının ({fmt_money(stmt_ocf, fin_curr)}) oldukça altındadır; uçak kiralama/amortisman sınıflandırması nedeniyle Net Borç/FAVÖK ({fmt_ratio(net_debt_to_ebitda)}) olduğundan yüksek görünebilir."
        )

    true_pb = None
    if price and book_value_raw and book_value_raw > 0:
        true_pb = price / (book_value_raw * fx_fin_to_price)
    elif info.get("priceToBook") and fin_curr == price_curr:
        true_pb = info.get("priceToBook")

    roe_raw = info.get("returnOnEquity")
    roe_formatted = fmt_pct(roe_raw)
    if roe_raw and roe_raw > 0.40:
        roe_formatted += " (Hisse geri alımları [buyback] kaynaklı düşük özsermaye etkisi)"

    # 3. Takvim Ayrıştırması: Sadece bugünden (20.10.2026) SONRAKİ tarihleri "Yaklaşan" kabul et!
    upcoming_events = {}
    past_events = {}
    try:
        cal = stock.calendar
        if isinstance(cal, dict):
            for k, v in cal.items():
                val_str = str(v)
                date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", val_str)
                if date_matches:
                    dt_obj = datetime.strptime(date_matches[0], "%Y-%m-%d")
                    if dt_obj.date() >= now_dt.date():
                        upcoming_events[f"Yaklaşan {k}"] = val_str
                    else:
                        past_events[f"Geçmiş {k} (Katalizör Değil)"] = val_str
                else:
                    upcoming_events[str(k)] = val_str
    except Exception:
        pass

    # 4. Insider İşlemleri Durumu (BIST vs ABD Ayrımı)
    insider_list = []
    insider_status_note = ""
    if ticker.endswith(".IS"):
        insider_status_note = "BIST hisseleri için yfinance üzerinden otomatik Form 4 verisi sağlanmamaktadır; pay alım/satım bildirimleri KAP araması üzerinden kontrol edilmektedir (Veri kaynağında yok != İşlem yok)."
    else:
        try:
            ins = stock.insider_transactions
            if ins is not None and not ins.empty:
                for _, row in ins.head(5).iterrows():
                    insider_name = str(row.get("Insider", "Yönetici"))
                    trans_text = str(row.get("Transaction", "İşlem"))
                    shares_val = str(row.get("Shares", ""))
                    val_usd = row.get("Value", None)
                    start_date = str(row.get("Start Date", ""))[:10]
                    val_str = fmt_money(float(val_usd), fin_curr) if pd.notna(val_usd) else ""
                    insider_list.append(f"{start_date}: {insider_name} - {trans_text} ({shares_val} adet, {val_str})")
            insider_status_note = f"SEC Form 4 / Insider tablosu kontrol edildi ({len(insider_list)} yakın işlem bulundu)."
        except Exception:
            insider_status_note = "Insider tablosu sorgulandı ancak veri alınamadı."

    emp_beta, bench_label = compute_empirical_beta(ticker)
    macro_data = get_macro_indicators(ticker)

    currency_note = (
        f"Hisse {price_curr} ile işlem görmekte, finansal tablolarını {fin_curr} olarak raporlamaktadır (Kur: {tr_num(fx_fin_to_price, 2)} ₺). Çarpanlar kur etkisinden arındırılmıştır."
        if price_curr != fin_curr
        else f"İşlem ve bilanço para birimi aynıdır ({price_curr})."
    )

    result = {
        "meta": {
            "ticker": ticker,
            "companyName": info.get("longName") or info.get("shortName") or ticker,
            "sector": info.get("sector", "Belirtilmemiş"),
            "priceCurrency": price_curr,
            "financialCurrency": fin_curr,
            "usdTryRate": round(usd_try_rate, 2),
            "currencyNote": currency_note,
            "empiricalBeta": emp_beta,
            "benchmarkName": bench_label,
            "betaFormatted": f"{tr_num(emp_beta, 2)} (Referans: {bench_label})",
            "consistencyFlags": consistency_flags,
            "insiderStatusNote": insider_status_note,
            "analysisReferenceDate": now_dt.strftime("%Y-%m-%d"),
            "dataTimestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        },
        "macroEnvironment": macro_data,
        "valuationStrings": {
            "Güncel Hisse Fiyatı": f"{tr_num(price, 2)} {price_curr}" if price else "Veri Yok",
            "52 Haftalık Fiyat Aralığı": f"{tr_num(info.get('fiftyTwoWeekLow', 0), 2)} - {tr_num(info.get('fiftyTwoWeekHigh', 0), 2)} {price_curr}",
            "Piyasa Değeri": fmt_money(market_cap, price_curr),
            "F/K (Trailing P/E)": fmt_ratio(info.get("trailingPE"), "x"),
            "İleri F/K (Forward P/E)": fmt_ratio(info.get("forwardPE"), "x"),
            "Gerçek PD/DD (Kur Düzeltmeli P/B)": fmt_ratio(true_pb, "x"),
            "Hisse Başı Defter Değeri": f"{tr_num(book_value_raw, 2)} {fin_curr}" if book_value_raw else "Bildirilmedi"
        },
        "profitabilityAndDebtStrings": {
            "Özsermaye Karlılığı (ROE)": roe_formatted,
            "Aktif Karlılığı (ROA)": fmt_pct(info.get("returnOnAssets")),
            "Brüt Kâr Marjı": fmt_pct(gross_margin),
            "Faaliyet Kâr Marjı (Tablo Tutarlı)": fmt_pct(op_margin),
            "Net Kâr Marjı (Tablo Tutarlı)": fmt_pct(net_margin),
            "Toplam Gelir (Orijinal Bilanço)": fmt_money(total_revenue_raw, fin_curr),
            "Toplam Gelir (TL/Fiyat Birimi Karşılığı)": fmt_money(total_revenue_raw * fx_fin_to_price, price_curr) if total_revenue_raw and price_curr != fin_curr else "Aynı Birim",
            "FAVÖK (EBITDA)": fmt_money(ebitda_raw, fin_curr),
            "İşletme Nakit Akışı (OCF)": fmt_money(stmt_ocf, fin_curr),
            "Toplam Nakit": fmt_money(total_cash_raw, fin_curr),
            "Toplam Borç": fmt_money(total_debt_raw, fin_curr),
            "Net Borç": fmt_money(net_debt_raw, fin_curr),
            "Net Borç / FAVÖK": fmt_ratio(net_debt_to_ebitda, "x")
        },
        "officialFinancialStatements": statements,
        "upcomingCatalystCalendar": upcoming_events,
        "pastEventsCalendar": past_events,
        "insiderTransactions": insider_list
    }
    set_cached(cache_key, result)
    return result

# ==========================================================
# 3. FORMÜL BAZLI DETERMİNİSTİK GÜVEN SKORU & VERİ KALİTESİ
# ==========================================================

def calculate_deterministic_confidence(data: dict, rag_stat: dict, news_list: list) -> tuple[int, str]:
    """
    Güven skorunu LLM'in keyfine bırakmaz; kaynak ağırlıkları, RAG doğrulaması
    ve rasyo tutarlılık bayraklarından matematiksel olarak hesaplar.
    """
    score = 45 # Baz puan (Yahoo Finance fiyat + temel API)
    notes = []

    # 1. Resmi Gelir/Bilanço tablosu derinliği (+15)
    if len(data.get("officialFinancialStatements", {})) >= 4:
        score += 15
        notes.append("Resmi Bilanço/Gelir Tablosu: Tam (+15)")
    else:
        notes.append("Tablo Derinliği: Kısıtlı (+0)")

    # 2. Doğrulanmış PDF Faaliyet Raporu RAG (+15)
    if rag_stat.get("hasRag") and rag_stat.get("isVerified"):
        score += 15
        notes.append(f"Doğrulanmış PDF RAG ({rag_stat['chunks']} chunk): Aktif (+15)")
    else:
        notes.append("Doğrulanmış PDF Faaliyet Raporu: Yok (+0)")

    # 3. Haber ve Bildirim Kaynak Kalitesi (Max +25)
    weights = [n.get("credibilityWeight", 0.25) for n in news_list]
    high_cred_count = sum(1 for w in weights if w >= 0.75)
    if high_cred_count >= 3:
        score += 25
        notes.append(f"Resmi Bildirim/Ajans Kaynağı ({high_cred_count} adet): Yüksek (+25)")
    elif high_cred_count >= 1:
        score += 12
        notes.append(f"Resmi/Ajans Kaynağı ({high_cred_count} adet): Orta (+12)")
    else:
        score -= 5
        notes.append("Haber Kaynakları: Düşük Ağırlıklı Blog/Yorum Ağırlıklı (-5)")

    # 4. Rasyo Tutarlılık Cezaları (Consistency Flags)
    flags = data["meta"].get("consistencyFlags", [])
    if flags:
        penalty = min(len(flags) * 15, 25)
        score -= penalty
        notes.append(f"Veri Tutarlılık Uyarısı ({len(flags)} çelişki tespit edildi): (-{penalty})")

    final_score = max(20, min(95, score))
    quality_summary = f"{data['meta']['currencyNote']} | " + " • ".join(notes)
    if flags:
        quality_summary += " | ⚠️ Tutarlılık Notu: " + " ".join(flags)

    return (final_score, quality_summary)

# ==========================================================
# 4. SEC EDGAR & KAP / HABER ÇEKİMİ
# ==========================================================

DENYLIST_DOMAINS_OR_PATHS = [
    "apps.apple.com", "play.google.com", "itunes.apple.com",
    "stockanalysis.com/stocks/", "finance.yahoo.com/quote/",
    "tradingview.com/symbols/", "investing.com/equities/",
    "pinterest.com", "tiktok.com", "facebook.com"
]

OFFICIAL_DOMAINS = [
    "sec.gov", "kap.org.tr", "investor.apple.com", "investor.turkishairlines.com", "ir.", "investor.", "investors."
]

TIER1_AGENCY_DOMAINS = [
    "reuters.com", "bloomberg.com", "wsj.com", "ft.com", "cnbc.com",
    "aa.com.tr", "foreks.com", "bloomberght.com", "ekonomim.com", "dunya.com"
]

def classify_and_filter_url(url: str, title: str) -> tuple[bool, str, float]:
    if not url:
        return (False, "", 0.0)
    u_low = url.lower()
    t_low = (title or "").lower()

    for bad in DENYLIST_DOMAINS_OR_PATHS:
        if bad in u_low and "/news" not in u_low and "press" not in u_low:
            return (False, "Filtrelendi", 0.0)

    if "app store" in t_low or "google play" in t_low:
        return (False, "Filtrelendi", 0.0)

    domain = urlparse(u_low).netloc
    if any(off in domain or off in u_low for off in OFFICIAL_DOMAINS):
        return (True, "Resmi Bildirim / Yatırımcı İlişkileri (KAP/SEC/IR)", 1.0)
    if any(ag in domain for ag in TIER1_AGENCY_DOMAINS):
        return (True, "Kurumsal Finans Ajansı", 0.80)
    if any(k in t_low for k in ["form 4", "insider", "share sale", "sec filing", "8-k", "10-k", "10-q", "kap", "pay alım"]):
        return (True, "Düzenleyici Bildirim / Insider Haberi", 0.70)
    return (True, "Piyasa Yorumu / Analiz Blogu", 0.25)

async def fetch_sec_edgar_direct_filings(ticker: str) -> list[dict]:
    if ticker.endswith(".IS"):
        return []

    cache_key = f"sec_edgar_v7_{ticker}"
    cached = get_cached(cache_key, 3600)
    if cached is not None:
        return cached

    headers = {
        "User-Agent": "FinAgentHub/7.0 (AkdenizUniversityMIS; contact@finagenthub.local)",
        "Accept": "application/json"
    }

    filings_out = []
    async with httpx.AsyncClient(headers=headers, timeout=12.0) as client:
        try:
            tickers_resp = await client.get("https://www.sec.gov/files/company_tickers.json")
            if tickers_resp.status_code == 200:
                t_map = tickers_resp.json()
                cik_str = None
                for _, item in t_map.items():
                    if item.get("ticker", "").upper() == ticker.upper():
                        cik_str = str(item.get("cik_str")).zfill(10)
                        break

                if cik_str:
                    sub_resp = await client.get(f"https://data.sec.gov/submissions/CIK{cik_str}.json")
                    if sub_resp.status_code == 200:
                        recent = sub_resp.json().get("filings", {}).get("recent", {})
                        forms = recent.get("form", [])
                        dates = recent.get("filingDate", [])
                        acc_nums = recent.get("accessionNumber", [])
                        primary_docs = recent.get("primaryDocument", [])
                        descriptions = recent.get("primaryDocDescription", [])

                        target_forms = {"10-K", "10-Q", "8-K", "4"}
                        form4_count = 0
                        for i, form_type in enumerate(forms):
                            if form_type in target_forms and len(filings_out) < 5:
                                if form_type == "4":
                                    if form4_count >= 2:
                                        continue
                                    form4_count += 1
                                acc_clean = acc_nums[i].replace("-", "")
                                doc_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik_str)}/{acc_clean}/{primary_docs[i]}"
                                desc = descriptions[i] if i < len(descriptions) and descriptions[i] else f"SEC Form {form_type}"
                                form_label = "Form 4 (Insider Hisse İşlemi)" if form_type == "4" else f"SEC Form {form_type}"
                                filings_out.append({
                                    "title": f"[RESMİ SEC EDGAR] {form_label} — {desc} ({dates[i]})",
                                    "snippet": f"Resmi SEC EDGAR bildirimi: Form {form_type}, Bildirim Tarihi: {dates[i]}.",
                                    "link": doc_url,
                                    "date": dates[i],
                                    "sourceType": "Resmi SEC EDGAR Bildirimi",
                                    "credibilityWeight": 1.0
                                })
        except Exception as e:
            print(f"[SEC EDGAR UYARISI] {e}")

    set_cached(cache_key, filings_out)
    return filings_out

async def fetch_curated_news_and_filings(ticker: str, company_name: str) -> list:
    cache_key = f"news_v7_{ticker}"
    cached = get_cached(cache_key, 1800)
    if cached is not None:
        return cached

    combined = []
    sec_filings = await fetch_sec_edgar_direct_filings(ticker)
    combined.extend(sec_filings)

    try:
        yf_news = yf.Ticker(ticker).news or []
        for n in yf_news[:4]:
            content = n.get("content", n)
            title = content.get("title") or n.get("title")
            link = (content.get("canonicalUrl") or {}).get("url") or n.get("link")
            pub_date = content.get("pubDate", "Güncel")[:10]
            if title and link:
                is_valid, s_type, weight = classify_and_filter_url(link, title)
                if is_valid:
                    combined.append({
                        "title": title,
                        "snippet": content.get("summary") or title,
                        "link": link,
                        "date": pub_date,
                        "sourceType": s_type,
                        "credibilityWeight": max(weight, 0.75)
                    })
    except Exception:
        pass

    if SERPER_API_KEY:
        is_bist = ticker.endswith(".IS")
        clean_t = ticker.replace(".IS", "")
        if is_bist:
            query = f'"{clean_t}" OR "{company_name}" (site:kap.org.tr OR "KAP" OR "pay alım satım" OR "özel durum" OR "faaliyet raporu" OR "bilanço") -site:apps.apple.com -site:play.google.com'
            gl, hl = "tr", "tr"
        else:
            query = f'"{clean_t}" "{company_name}" ("investor relations" OR "8-K" OR "10-Q" OR "Form 4" OR "earnings" OR "Reuters" OR "Bloomberg") -site:apps.apple.com -site:play.google.com'
            gl, hl = "us", "en"

        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
                    json={"q": query, "gl": gl, "hl": hl, "num": 8, "tbs": "qdr:m"},
                    timeout=12.0
                )
                for item in resp.json().get("organic", []):
                    link = item.get("link", "")
                    title = item.get("title", "")
                    is_valid, s_type, weight = classify_and_filter_url(link, title)
                    if is_valid and not any(x["link"] == link for x in combined):
                        combined.append({
                            "title": title,
                            "snippet": item.get("snippet", ""),
                            "link": link,
                            "date": item.get("date", "Son 1 Ay"),
                            "sourceType": s_type,
                            "credibilityWeight": weight
                        })
            except Exception:
                pass

    combined.sort(key=lambda x: x["credibilityWeight"], reverse=True)
    final_list = combined[:8]
    for idx, item in enumerate(final_list):
        item["refId"] = f"[{idx + 2}]"

    set_cached(cache_key, final_list)
    return final_list

# ==========================================================
# 5. AJANLAR (SIFIR UYDURMA ATIF, TUTARLILIK BİLİNCİ)
# ==========================================================

def run_agent_1_fundamental(client: genai.Client, ticker: str, data: dict, rag_chunks: list, rag_stat: dict) -> str:
    if rag_chunks and rag_stat.get("isVerified"):
        allowed_rag_refs = ", ".join([f"[Faaliyet Raporu, s.{c['page']}]" for c in rag_chunks])
        rag_section = f"DOĞRULANMIŞ PDF ({rag_stat.get('fileName')}) PARÇALARI (İzin verilen atıflar: {allowed_rag_refs}):\n" + json.dumps(rag_chunks, ensure_ascii=False, indent=2)
    else:
        rag_section = "DOĞRULANMIŞ PDF FAALİYET RAPORU YÜKLENMEMİŞTİR. KESİNLİKLE [Faaliyet Raporu...] ŞEKLİNDE ATIF KULLANMA! Yalnızca [1] kullan."

    prompt = f"""
    Sen Kıdemli bir Kurumsal Finans Analistisin. {ticker} ({data['meta']['companyName']}) için hesaplanmış finansal tabloları ve çarpanları incele.

    KESİN KURALLAR:
    1. Selamlama cümlesi KULLANMA. Tüm sayılarda Türkçe formatı (virgül ondalık, örn: %10,19 veya 6,08x) koru.
    2. KAYNAK KURALI: Tablo ve API verileri için SADECE `[1]` yaz. Eğer aşağıda doğrulanmış PDF parçası yoksa ASLA faaliyet raporu veya sayfa numarası uydurma! Kaynak yoksa iddia kurma.
    3. TUTARLILIK UYARILARI: `consistencyFlags` içinde uyarı varsa (örn: Faaliyet marjı ile Net marj farkı veya FAVÖK/Nakit Akışı farkı), bunu mutlaka açıkla ve okuyucuyu uyar.
    4. Türkçe Markdown olarak şu 3 başlıkla yaz:
       ### 1. Değerleme Çarpanları, Beta ve Para Birimi Normalizasyonu
       ### 2. Gelir Tablosu, Bilanço, Nakit Akışı ve Tutarlılık Analizi
       ### 3. Takvim, İçeriden İşlemler Durumu ve Belge Bulguları

    VERİLER [1]:
    {json.dumps(data, ensure_ascii=False, indent=2)}

    RAG BELGE DURUMU:
    {rag_section}
    """
    res = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return res.text

def run_agent_2_sentiment(client: genai.Client, ticker: str, data: dict, news_list: list) -> str:
    is_bist = ticker.endswith(".IS")
    reg_name = "KAP" if is_bist else "SEC EDGAR (10-K / 10-Q / 8-K / Form 4)"
    valid_refs = [n["refId"] for n in news_list]

    prompt = f"""
    Sen Kurumsal Piyasa İstihbarat ve Düzenleyici Bildirim Analistisin. Bugünün Tarihi: {data['meta']['analysisReferenceDate']} (20.10.2026).

    KESİN KURALLAR:
    1. Selamlama KULLANMA. Sadece sana verilen kaynak numaralarını ({', '.join(valid_refs)}) kullan; listede olmayan kaynak uydurma.
    2. INSIDER DURUMU: `{data['meta']['insiderStatusNote']}`. Eğer veri kaynağında BIST için otomatik insider verisi yoksa "işlem yapılmadı/nötr" diye uydurma; "otomatik insider veri kaynağı mevcut değildir, KAP bildirimleri esastır" diye belirt.
    3. TARİH DOĞRULAMASI: Bildirim tarihi ile finansal dönem tarihini karıştırma (Örn: 30 Eylül'de biten 9 aylık bilanço 1 Ekim'de yayımlanmaz; 1 Ekim'deki haber geçmiş dönem raporu veya beklenti haberidir).
    4. Türkçe Markdown olarak şu 2 başlıkla yaz:
       ### 1. Resmi Bildirimler ({reg_name}) ve Pay Alım-Satım (Insider) Durumu
       ### 2. Kaynak Ağırlıklı Haber Akışı ve Duyarlılık Analizi

    AĞIRLIKLI KAYNAKLAR:
    {json.dumps(news_list, ensure_ascii=False, indent=2)}

    YÖNETİCİ İŞLEMLERİ [1]:
    {json.dumps(data['insiderTransactions'], ensure_ascii=False, indent=2)}
    """
    res = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return res.text

def run_agent_3_structured_strategist(
    client: genai.Client, ticker: str, data: dict, fundamental_rep: str, sentiment_rep: str, req: AnalyzeRequest, valid_refs_list: list[str]
) -> dict:
    if req.totalPositionsCount < 2:
        port_structure_note = "Portföyde yalnızca tek varlık bulunmaktadır (%100 ağırlık)."
    elif req.maxPortfolioWeightPct >= 35.0:
        port_structure_note = (
            f"Portföyde toplam {req.totalPositionsCount} varlık vardır; Efektif Varlık Sayısı (N_eff) {tr_num(req.effectiveN, 2)}'dir. "
            f"Portföyün %{tr_num(req.maxPortfolioWeightPct, 1)}'i {req.largestPositionTicker} pozisyonundadır, "
            f"incelenen {ticker} hissesinin ağırlığı ise %{tr_num(req.portfolioWeightPct, 1)}'dir (Yüksek tek varlık yoğunlaşması)."
        )
    else:
        port_structure_note = (
            f"Portföyde {req.totalPositionsCount} varlık bulunmaktadır (En büyük ağırlık: %{tr_num(req.maxPortfolioWeightPct, 1)}, "
            f"{ticker} ağırlığı: %{tr_num(req.portfolioWeightPct, 1)}, Efektif Varlık Sayısı: {tr_num(req.effectiveN, 2)})."
        )

    prompt = f"""
    Sen Kurumsal Portföy Risk Gözlemcisi ve Baş Analistsin. Bugünün Tarihi: {data['meta']['analysisReferenceDate']}.
    İncelenen Hisse: {ticker} ({data['meta']['companyName']})
    Piyasaya Özel Makro Göstergeler [1]: {json.dumps(data['macroEnvironment'], ensure_ascii=False)}
    Yaklaşan Takvim: {json.dumps(data['upcomingCatalystCalendar'], ensure_ascii=False)}
    Tutarlılık Uyarıları: {json.dumps(data['meta']['consistencyFlags'], ensure_ascii=False)}

    PORTFÖY DAĞILIM VERİSİ:
    {port_structure_note}

    KESİN KURALLAR:
    1. İZİN VERİLEN KAYNAK ATIFLARI: {', '.join(valid_refs_list)}. Listede olmayan hiçbir atfı kullanma; kaynak yoksa iddia kurma.
    2. MEVZUAT / SPK İDDİASI YASAĞI: ASLA "SPK uyumlu eşik", "SPK'ya göre kabul edilebilir sınır" veya herhangi bir yasal/mevzuat eşiği iddiası KURMA! Yoğunlaşma ve risk oranlarını sadece matematiksel portföy gözlemi olarak ifade et.
    3. PİYASA BAZLI MAKRO KURALI: `macroContextSummary` içinde SADECE sana yukarıda verilen `{data['macroEnvironment']['Piyasa']}` makro verilerini kullan. ABD hissesi analiz edilirken Türkiye/TCMB/TL'den bahsetme; BIST hissesi analiz edilirken de veri setinde olmayan faiz/enflasyon rakamı uydurma.
    4. YÖNLENDİRME YASAĞI: Al/sat/tut veya tavsiye dili kullanma; sadece nötr analitik gözlem yaz.

    --- AJAN 1 RAPORU ---
    {fundamental_rep}

    --- AJAN 2 RAPORU ---
    {sentiment_rep}
    """
    res = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=StructuredStrategyOutput,
        ),
    )
    return json.loads(res.text)

# ==========================================================
# 6. CANLI FİYAT, AKILLI SEMBOL, RAG SİLME & GRAFİK API'LERİ
# ==========================================================

@app.get("/api/agent/resolve-ticker/{raw_symbol}")
async def resolve_ticker(raw_symbol: str):
    sym = raw_symbol.upper().strip()
    if sym.endswith(".IS"):
        return {"resolvedTicker": sym, "market": "BIST", "currency": "TRY"}

    if 3 <= len(sym) <= 5 and sym.isalpha():
        try:
            bist_candidate = f"{sym}.IS"
            bist_info = yf.Ticker(bist_candidate).fast_info
            if bist_info.get("lastPrice") and bist_info.get("lastPrice") > 0:
                return {"resolvedTicker": bist_candidate, "market": "BIST", "currency": "TRY"}
        except Exception:
            pass

    try:
        us_info = yf.Ticker(sym).fast_info
        if us_info.get("lastPrice") and us_info.get("lastPrice") > 0:
            return {"resolvedTicker": sym, "market": "GLOBAL", "currency": us_info.get("currency", "USD")}
    except Exception:
        pass

    if len(sym) == 5:
        return {"resolvedTicker": f"{sym}.IS", "market": "BIST", "currency": "TRY"}
    return {"resolvedTicker": sym, "market": "GLOBAL", "currency": "USD"}

@app.delete("/api/agent/rag/{ticker}")
async def delete_rag_document(ticker: str):
    removed = clear_rag_store(ticker)
    return {"removed": removed, "ticker": ticker}

@app.post("/api/agent/live-quotes")
async def get_live_quotes(req: QuotesRequest):
    usd_try = get_fx_rate("USD", "TRY")
    quotes = {}
    for t in req.tickers:
        try:
            st = yf.Ticker(t)
            info = st.info or {}
            price = info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
            prev_close = info.get("previousClose") or price
            curr = info.get("currency", "TRY" if t.endswith(".IS") else "USD")
            fin_curr = info.get("financialCurrency") or curr
            daily_change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0.0
            rag_st = get_rag_status(t)
            emp_beta, bench_label = compute_empirical_beta(t)

            quotes[t] = {
                "price": round(float(price), 2),
                "currency": curr,
                "financialCurrency": fin_curr,
                "dailyChangePct": round(float(daily_change_pct), 2),
                "priceInTry": round(float(price * (usd_try if curr == "USD" else 1.0)), 2),
                "beta": emp_beta,
                "benchmarkName": bench_label,
                "ragChunks": rag_st["chunks"],
                "ragFileName": rag_st["fileName"],
                "ragWarning": rag_st["warning"]
            }
        except Exception:
            quotes[t] = {"price": 0.0, "currency": "TRY", "financialCurrency": "TRY", "dailyChangePct": 0.0, "priceInTry": 0.0, "beta": 1.0, "benchmarkName": "BIST 100", "ragChunks": 0}

    return {"usdTry": round(usd_try, 2), "quotes": quotes}

@app.post("/api/agent/market-analytics")
async def get_market_analytics(req: ChartRequest):
    ticker = req.ticker
    benchmark = "XU100.IS" if ticker.endswith(".IS") else "^GSPC"
    bench_name = "BIST 100" if ticker.endswith(".IS") else "S&P 500"

    try:
        s_raw = yf.Ticker(ticker).history(period="6mo")["Close"]
        b_raw = yf.Ticker(benchmark).history(period="6mo")["Close"]

        s_raw.index = s_raw.index.tz_localize(None).normalize()
        b_raw.index = b_raw.index.tz_localize(None).normalize()

        # Ortak tarihlerde Inner Join
        df = pd.DataFrame({"stock": s_raw, "bench": b_raw}).dropna()
        if df.empty:
            return {"series": [], "volatilityPct": 0, "beta": 1.0, "benchmarkName": bench_name, "correlations": {}}

        df["stockNorm"] = (df["stock"] / df["stock"].iloc[0]) * 100.0
        df["benchNorm"] = (df["bench"] / df["bench"].iloc[0]) * 100.0

        rets = df[["stock", "bench"]].pct_change().dropna()
        annual_vol = float(rets["stock"].std() * np.sqrt(252) * 100.0) if len(rets) > 2 else 0.0

        # Ortak Günlük Getirilerden Gerçek Beta
        emp_beta = 1.0
        if len(rets) > 15 and np.var(rets["bench"]) > 0:
            emp_beta = round(float(np.cov(rets["stock"], rets["bench"])[0, 1] / np.var(rets["bench"])), 2)

        correlations = {}
        for other_t in req.portfolioTickers:
            if other_t == ticker:
                continue
            try:
                o_raw = yf.Ticker(other_t).history(period="6mo")["Close"]
                o_raw.index = o_raw.index.tz_localize(None).normalize()
                comb = pd.DataFrame({"a": s_raw.pct_change(), "b": o_raw.pct_change()}).dropna()
                if len(comb) > 10:
                    correlations[other_t] = round(float(comb["a"].corr(comb["b"])), 2)
            except Exception:
                pass

        step = max(len(df) // 35, 1)
        sampled = df.iloc[::step]
        if sampled.index[-1] != df.index[-1]:
            sampled = pd.concat([sampled, df.iloc[[-1]]])

        series = [
            {
                "date": idx.strftime("%d.%m.%Y"),
                "shortDate": idx.strftime("%d.%m"),
                "price": round(float(row["stock"]), 2),
                "stockNorm": round(float(row["stockNorm"]), 1),
                "benchNorm": round(float(row["benchNorm"]), 1)
            }
            for idx, row in sampled.iterrows()
        ]

        return {
            "ticker": ticker,
            "benchmarkName": bench_name,
            "volatilityPct": round(annual_vol, 1),
            "beta": emp_beta,
            "stockReturn6mPct": round(float(df["stockNorm"].iloc[-1] - 100.0), 1),
            "benchReturn6mPct": round(float(df["benchNorm"].iloc[-1] - 100.0), 1),
            "correlations": correlations,
            "series": series
        }
    except Exception as e:
        return {"series": [], "volatilityPct": 0, "beta": 1.0, "benchmarkName": bench_name, "error": str(e), "correlations": {}}

@app.post("/api/agent/upload-pdf")
async def upload_company_pdf(tickerSymbol: str = Form(...), file: UploadFile = File(...)):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY eksik.")

    file_path = os.path.join(UPLOAD_DIR, file.filename)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    client = genai.Client(api_key=GEMINI_API_KEY)
    try:
        st = yf.Ticker(tickerSymbol)
        comp_name = (st.info or {}).get("longName") or tickerSymbol
        stats = ingest_pdf_to_vector_store(client, tickerSymbol, comp_name, file_path, file.filename)
        return {
            "message": "Doğrulandı ve Vektörleştirildi",
            "ticker": tickerSymbol,
            "fileName": file.filename,
            "vectorizedChunks": stats["totalChunksGenerated"],
            "validationNote": stats.get("validationNote"),
            "stats": stats
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ==========================================================
# 7. PARALEL İŞÇİ VE SONRASI ATIF DENETİMİ
# ==========================================================

async def notify_dotnet_progress(job_id: str, step_status: str):
    async with httpx.AsyncClient() as http_client:
        try:
            await http_client.post(DOTNET_WEBHOOK_URL, json={
                "jobId": job_id,
                "isSuccess": True,
                "statusOverride": step_status
            }, timeout=10.0)
        except Exception:
            pass

async def process_analysis_job(req: AnalyzeRequest):
    job_id = req.jobId
    ticker = req.tickerSymbol
    start_time = time.time()
    callback_payload = {
        "jobId": job_id,
        "isSuccess": False,
        "fundamentalReport": None,
        "sentimentReport": None,
        "synthesisReport": None,
        "sourcesJson": None,
        "errorMessage": None
    }

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)

        await notify_dotnet_progress(job_id, "Adım 1/2 (Paralel): Tablolar, Tutarlılık, SEC/KAP ve Doğrulanmış RAG Çekiliyor...")
        computed_data = await asyncio.to_thread(fetch_and_compute_deterministic_metrics, ticker)
        company_name = computed_data["meta"]["companyName"]
        rag_stat = get_rag_status(ticker)

        rag_query = f"{company_name} gelir tablosu bilanço ciro favök net kar borç yatırımlar riskler"
        rag_chunks = await asyncio.to_thread(search_company_documents, client, ticker, rag_query, 5)
        news_list = await fetch_curated_news_and_filings(ticker, company_name)

        sources = [
            {
                "refId": "[1]",
                "type": "Resmi Finansal Tablolar & Makro",
                "name": f"Yahoo Finance & Resmi Bilanço/Gelir Tablosu ({ticker} - {computed_data['meta']['financialCurrency']})",
                "weight": 1.0,
                "url": f"https://finance.yahoo.com/quote/{ticker}/financials"
            }
        ]
        for r in rag_chunks:
            sources.append({
                "refId": f"[Faaliyet Raporu, s.{r['page']}]",
                "type": "Doğrulanmış PDF/RAG",
                "name": f"{r['source_file']} (Sayfa {r['page']})",
                "weight": 1.0,
                "url": "#rag"
            })
        for n in news_list:
            if n.get("link"):
                sources.append({
                    "refId": n["refId"],
                    "type": n["sourceType"],
                    "name": f"{n['title']} ({n['date']})",
                    "weight": n["credibilityWeight"],
                    "url": n["link"]
                })

        valid_ref_set = {s["refId"] for s in sources}
        valid_ref_list = [s["refId"] for s in sources]

        await notify_dotnet_progress(job_id, "Adım 1/2 (Paralel): Ajan 1 (Bilanço) ve Ajan 2 (KAP/SEC/Haber) Eşzamanlı Çalışıyor...")
        raw_fund, raw_sent = await asyncio.gather(
            asyncio.to_thread(run_agent_1_fundamental, client, ticker, computed_data, rag_chunks, rag_stat),
            asyncio.to_thread(run_agent_2_sentiment, client, ticker, computed_data, news_list)
        )

        # Hazır biçimli yüzdelerden doğrulama eşlemesi oluştur
        known_pct_fixes = {}
        raw_roe = computed_data["profitabilityAndDebtStrings"].get("Özsermaye Karlılığı (ROE)", "")
        pct_match = re.search(r"%(\d+),(\d+)", raw_roe)
        if pct_match:
            correct_str = pct_match.group(0)
            val_num = float(f"{pct_match.group(1)}.{pct_match.group(2)}")
            if val_num > 20.0:
                wrong_num = val_num / 100.0
                known_pct_fixes[f"%{tr_num(wrong_num, 2)}"] = correct_str

        # Atıf ve yüzde doğrulaması
        fundamental_report = verify_citations_and_percentages(raw_fund, valid_ref_set, known_pct_fixes)
        sentiment_report = verify_citations_and_percentages(raw_sent, valid_ref_set, known_pct_fixes)

        await notify_dotnet_progress(job_id, "Adım 2/2: Baş Stratejist Sentezi ve Deterministik Güven Skoru Hesaplanıyor...")
        structured_strategy = await asyncio.to_thread(
            run_agent_3_structured_strategist,
            client, ticker, computed_data, fundamental_report, sentiment_report, req, valid_ref_list
        )

        # Strateji kartlarındaki atıf ve yüzdeleri de doğrula
        for list_key in ["currentStrengths", "forwardCatalysts", "keyRisks", "whatChangesTheView"]:
            for item in structured_strategy.get(list_key, []):
                item["detail"] = verify_citations_and_percentages(item.get("detail", ""), valid_ref_set, known_pct_fixes)

        for field in ["macroContextSummary", "positionRiskObservation", "alignmentSummary"]:
            structured_strategy[field] = verify_citations_and_percentages(
                structured_strategy.get(field, ""), valid_ref_set, known_pct_fixes
            )

        # Deterministik Güven Skoru ve Veri Kalitesi Notunu Hesapla (LLM'in uydurmasını engeller!)
        det_conf_score, det_quality_note = calculate_deterministic_confidence(computed_data, rag_stat, news_list)
        structured_strategy["confidenceScore"] = det_conf_score
        structured_strategy["dataQualityNote"] = det_quality_note
        structured_strategy["consistencyFlags"] = computed_data["meta"]["consistencyFlags"]

        elapsed_sec = round(time.time() - start_time, 1)
        structured_strategy["schemaVersion"] = 4
        structured_strategy["analysisDurationSec"] = elapsed_sec
        structured_strategy["dataTimestampUtc"] = computed_data["meta"]["dataTimestamp"]
        structured_strategy["portfolioWeightPct"] = round(req.portfolioWeightPct, 1)

        callback_payload["isSuccess"] = True
        callback_payload["fundamentalReport"] = fundamental_report
        callback_payload["sentimentReport"] = sentiment_report
        callback_payload["synthesisReport"] = json.dumps(structured_strategy, ensure_ascii=False)
        callback_payload["sourcesJson"] = json.dumps(sources, ensure_ascii=False)

    except Exception as e:
        callback_payload["isSuccess"] = False
        callback_payload["errorMessage"] = str(e)

    async with httpx.AsyncClient() as http_client:
        await http_client.post(DOTNET_WEBHOOK_URL, json=callback_payload, timeout=30.0)

@app.post("/api/agent/analyze", status_code=202)
async def start_analysis(request: AnalyzeRequest, background_tasks: BackgroundTasks):
    background_tasks.add_task(process_analysis_job, request)
    return {"message": "Paralel analiz başlatıldı.", "jobId": request.jobId}
