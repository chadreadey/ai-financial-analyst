"""
XBRL data parser for SEC company facts.

Transforms raw XBRL JSON from the SEC API into structured
DataFrames and computed financial metrics that agents consume.
"""

from typing import Any, Dict, List, Optional

import pandas as pd

from utils import format_money


# Common US-GAAP concepts we extract
INCOME_STATEMENT_CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "CostOfGoodsSold",
    "CostOfGoodsAndServicesSold",
    "CostOfRevenue",
    "GrossProfit",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "EarningsPerShareBasic",
    "EarningsPerShareDiluted",
    "ResearchAndDevelopmentExpense",
    "SellingGeneralAndAdministrativeExpense",
]

BALANCE_SHEET_CONCEPTS = [
    "Assets",
    "AssetsCurrent",
    "Liabilities",
    "LiabilitiesCurrent",
    "StockholdersEquity",
    "CashAndCashEquivalentsAtCarryingValue",
    "ShortTermInvestments",
    "AccountsReceivableNetCurrent",
    "InventoryNet",
    "LongTermDebt",
    "LongTermDebtNoncurrent",
    "ShortTermBorrowings",
    "CommonStockSharesOutstanding",
]

CASH_FLOW_CONCEPTS = [
    "NetCashProvidedByUsedInOperatingActivities",
    "NetCashProvidedByUsedInInvestingActivities",
    "NetCashProvidedByUsedInFinancingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "DepreciationDepletionAndAmortization",
    "ShareBasedCompensation",
    "PaymentsOfDividends",
    "PaymentsForRepurchaseOfCommonStock",
]


class XBRLParser:
    """Parse SEC XBRL company facts into structured financial data."""

    def __init__(self, company_facts: Dict[str, Any]):
        """
        Args:
            company_facts: Raw JSON from SEC company facts API.
        """
        self.raw = company_facts
        self.facts = company_facts.get("facts", {})
        self.us_gaap = self.facts.get("us-gaap", {})
        self.entity_name = company_facts.get("entityName", "Unknown")

    def _extract_concept(
        self,
        concept: str,
        unit_filter: str = "USD",
        form_filter: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract a single XBRL concept into a DataFrame.
        Returns columns: [end, val, form, filed, fiscal_year, fiscal_period].
        """
        if form_filter is None:
            form_filter = ["10-K", "10-Q"]

        concept_data = self.us_gaap.get(concept, {})
        if not concept_data:
            return pd.DataFrame()

        units = concept_data.get("units", {})
        records = units.get(unit_filter, [])
        if not records:
            # Try "shares" for per-share or share count concepts
            records = units.get("shares", [])
        if not records:
            # Try USD/shares for EPS
            records = units.get("USD/shares", [])
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)

        # Filter to annual/quarterly filings
        if "form" in df.columns:
            df = df[df["form"].isin(form_filter)]

        # Keep only point-in-time or full-period entries
        # (filter out quarterly fragments for income/cash flow items)
        if "start" in df.columns and "end" in df.columns:
            df["duration_days"] = (
                pd.to_datetime(df["end"]) - pd.to_datetime(df["start"])
            ).dt.days
            # For 10-K, keep ~365 day periods; for 10-Q keep ~90 day periods
            df_annual = df[
                (df["form"] == "10-K") & (df["duration_days"] > 300)
            ]
            df_quarterly = df[
                (df["form"] == "10-Q") & (df["duration_days"] < 120)
            ]
            df = pd.concat([df_annual, df_quarterly])

        if df.empty:
            return df

        df = df.sort_values("end", ascending=False)

        # Add fiscal year/period info
        if "fy" in df.columns:
            df = df.rename(columns={"fy": "fiscal_year", "fp": "fiscal_period"})
        if "end" in df.columns:
            df["end"] = pd.to_datetime(df["end"])

        return df[
            [c for c in ["end", "val", "form", "filed", "fiscal_year", "fiscal_period"] if c in df.columns]
        ].reset_index(drop=True)

    def get_income_statement(self, years: int = 5) -> Dict[str, pd.DataFrame]:
        """Extract income statement line items for the last N years."""
        results = {}
        for concept in INCOME_STATEMENT_CONCEPTS:
            df = self._extract_concept(concept, form_filter=["10-K"])
            if not df.empty:
                results[concept] = df.head(years)
        return results

    def get_balance_sheet(self, years: int = 5) -> Dict[str, pd.DataFrame]:
        """Extract balance sheet line items for the last N years."""
        results = {}
        for concept in BALANCE_SHEET_CONCEPTS:
            df = self._extract_concept(concept, form_filter=["10-K"])
            if not df.empty:
                results[concept] = df.head(years)
        return results

    def get_cash_flow(self, years: int = 5) -> Dict[str, pd.DataFrame]:
        """Extract cash flow statement items for the last N years."""
        results = {}
        for concept in CASH_FLOW_CONCEPTS:
            df = self._extract_concept(concept, form_filter=["10-K"])
            if not df.empty:
                results[concept] = df.head(years)
        return results

    def _latest_annual_value(self, concept: str) -> Optional[float]:
        """Get the most recent 10-K value for a concept."""
        df = self._extract_concept(concept, form_filter=["10-K"])
        if df.empty:
            return None
        return float(df.iloc[0]["val"])

    def _annual_series(self, concept: str, years: int = 8) -> pd.DataFrame:
        """Get annual 10-K series for a concept, sorted newest-first."""
        df = self._extract_concept(concept, form_filter=["10-K"])
        if df.empty:
            return df
        return df.head(years)

    def _resolve_revenue_df(self, form_filter: Optional[List[str]] = None) -> pd.DataFrame:
        if form_filter is None:
            form_filter = ["10-K"]
        for concept in [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
        ]:
            df = self._extract_concept(concept, form_filter=form_filter)
            if not df.empty:
                return df
        return pd.DataFrame()

    def compute_metrics(self) -> Dict[str, Any]:
        """
        Compute derived financial metrics from XBRL data.
        Returns a dict of metric_name → value (or None if unavailable).
        """
        metrics: Dict[str, Any] = {}

        # Revenue
        revenue = (
            self._latest_annual_value("Revenues")
            or self._latest_annual_value("RevenueFromContractWithCustomerExcludingAssessedTax")
            or self._latest_annual_value("SalesRevenueNet")
        )
        metrics["revenue"] = revenue

        # Net income
        net_income = self._latest_annual_value("NetIncomeLoss")
        metrics["net_income"] = net_income

        # Gross profit
        gross_profit = self._latest_annual_value("GrossProfit")
        metrics["gross_profit"] = gross_profit

        # Operating income
        operating_income = self._latest_annual_value("OperatingIncomeLoss")
        metrics["operating_income"] = operating_income

        # Margins
        if revenue and revenue != 0:
            if gross_profit is not None:
                metrics["gross_margin"] = round(gross_profit / revenue, 4)
            if operating_income is not None:
                metrics["operating_margin"] = round(operating_income / revenue, 4)
            if net_income is not None:
                metrics["net_margin"] = round(net_income / revenue, 4)

        # Balance sheet items
        total_assets = self._latest_annual_value("Assets")
        total_liabilities = self._latest_annual_value("Liabilities")
        equity = self._latest_annual_value("StockholdersEquity")
        cash = self._latest_annual_value("CashAndCashEquivalentsAtCarryingValue")
        long_term_debt = (
            self._latest_annual_value("LongTermDebt")
            or self._latest_annual_value("LongTermDebtNoncurrent")
        )
        metrics["total_assets"] = total_assets
        metrics["total_liabilities"] = total_liabilities
        metrics["stockholders_equity"] = equity
        metrics["cash"] = cash
        metrics["long_term_debt"] = long_term_debt

        # Leverage ratios
        if equity and equity != 0:
            if total_liabilities is not None:
                metrics["debt_to_equity"] = round(total_liabilities / equity, 4)
            if net_income is not None:
                metrics["roe"] = round(net_income / equity, 4)

        if total_assets and total_assets != 0 and net_income is not None:
            metrics["roa"] = round(net_income / total_assets, 4)

        # Cash flow
        operating_cf = self._latest_annual_value(
            "NetCashProvidedByUsedInOperatingActivities"
        )
        capex = self._latest_annual_value(
            "PaymentsToAcquirePropertyPlantAndEquipment"
        )
        metrics["operating_cash_flow"] = operating_cf
        metrics["capex"] = capex

        # Free cash flow
        if operating_cf is not None and capex is not None:
            metrics["free_cash_flow"] = operating_cf - capex

        # EPS
        metrics["eps_basic"] = self._latest_annual_value("EarningsPerShareBasic")
        metrics["eps_diluted"] = self._latest_annual_value("EarningsPerShareDiluted")

        # Shares outstanding
        metrics["shares_outstanding"] = self._latest_annual_value(
            "CommonStockSharesOutstanding"
        )

        # Revenue growth (YoY) and multi-year CAGRs
        revenue_df = self._resolve_revenue_df(form_filter=["10-K"])
        if len(revenue_df) >= 2:
            latest = float(revenue_df.iloc[0]["val"])
            prior = float(revenue_df.iloc[1]["val"])
            if prior != 0:
                metrics["revenue_growth_yoy"] = round((latest - prior) / prior, 4)

        metrics["revenue_cagr_3y"] = self._compute_cagr(revenue_df, 3)
        metrics["revenue_cagr_5y"] = self._compute_cagr(revenue_df, 5)

        ni_df = self._annual_series("NetIncomeLoss", years=8)
        metrics["net_income_cagr_3y"] = self._compute_cagr(ni_df, 3)
        metrics["net_income_cagr_5y"] = self._compute_cagr(ni_df, 5)

        oi_df = self._annual_series("OperatingIncomeLoss", years=8)
        rev_cagr = metrics.get("revenue_cagr_5y")
        oi_cagr = self._compute_cagr(oi_df, 5)
        if rev_cagr is not None and oi_cagr is not None and rev_cagr != 0:
            metrics["operating_leverage_5y"] = round(oi_cagr / rev_cagr, 2)
        else:
            metrics["operating_leverage_5y"] = None

        return metrics

    @staticmethod
    def _compute_cagr(df: pd.DataFrame, years: int) -> Optional[float]:
        if df.empty or len(df) < years + 1:
            return None
        end_val = float(df.iloc[0]["val"])
        start_val = float(df.iloc[years]["val"])
        if start_val <= 0 or end_val <= 0:
            return None
        return round((end_val / start_val) ** (1.0 / years) - 1, 4)

    def get_historical_margins(self, years: int = 8) -> List[Dict[str, Any]]:
        """Return per-year gross/operating/net margins."""
        revenue_df = self._resolve_revenue_df(form_filter=["10-K"]).head(years)
        gp_df = self._annual_series("GrossProfit", years)
        oi_df = self._annual_series("OperatingIncomeLoss", years)
        ni_df = self._annual_series("NetIncomeLoss", years)

        if revenue_df.empty:
            return []

        results = []
        for _, rev_row in revenue_df.iterrows():
            fy = rev_row.get("fiscal_year")
            end = str(rev_row["end"].date()) if pd.notna(rev_row["end"]) else None
            rev = float(rev_row["val"])
            if rev == 0:
                continue

            entry: Dict[str, Any] = {"fiscal_year": fy, "period_end": end}

            for label, src_df, concept_col in [
                ("gross_margin", gp_df, "val"),
                ("operating_margin", oi_df, "val"),
                ("net_margin", ni_df, "val"),
            ]:
                matched = src_df[src_df["fiscal_year"] == fy] if not src_df.empty and "fiscal_year" in src_df.columns else pd.DataFrame()
                if not matched.empty:
                    entry[label] = round(float(matched.iloc[0][concept_col]) / rev, 4)

            results.append(entry)
        return results

    def get_historical_cash_flow(self, years: int = 8) -> List[Dict[str, Any]]:
        """Return per-year operating CF, capex, and FCF."""
        ocf_df = self._annual_series("NetCashProvidedByUsedInOperatingActivities", years)
        capex_df = self._annual_series("PaymentsToAcquirePropertyPlantAndEquipment", years)

        if ocf_df.empty:
            return []

        results = []
        for _, row in ocf_df.iterrows():
            fy = row.get("fiscal_year")
            end = str(row["end"].date()) if pd.notna(row["end"]) else None
            ocf = float(row["val"])

            entry: Dict[str, Any] = {
                "fiscal_year": fy,
                "period_end": end,
                "operating_cf": ocf,
            }

            matched = capex_df[capex_df["fiscal_year"] == fy] if not capex_df.empty and "fiscal_year" in capex_df.columns else pd.DataFrame()
            if not matched.empty:
                cx = float(matched.iloc[0]["val"])
                entry["capex"] = cx
                entry["fcf"] = ocf - cx

            results.append(entry)
        return results

    def compute_quarterly_metrics(self, quarters: int = 8) -> List[Dict[str, Any]]:
        """Extract the last N quarters of key income metrics from 10-Q filings."""
        revenue_df = self._resolve_revenue_df(form_filter=["10-Q"]).head(quarters)
        ni_df = self._extract_concept("NetIncomeLoss", form_filter=["10-Q"]).head(quarters)
        oi_df = self._extract_concept("OperatingIncomeLoss", form_filter=["10-Q"]).head(quarters)
        eps_df = self._extract_concept("EarningsPerShareDiluted", form_filter=["10-Q"]).head(quarters)

        if revenue_df.empty:
            return []

        results = []
        for _, row in revenue_df.iterrows():
            fy = row.get("fiscal_year")
            fp = row.get("fiscal_period")
            end = str(row["end"].date()) if pd.notna(row["end"]) else None
            rev = float(row["val"])

            entry: Dict[str, Any] = {
                "fiscal_year": fy,
                "fiscal_period": fp,
                "period_end": end,
                "revenue": rev,
            }

            for label, src_df in [("net_income", ni_df), ("operating_income", oi_df), ("eps_diluted", eps_df)]:
                if src_df.empty:
                    continue
                match = src_df[(src_df.get("fiscal_year", pd.Series()) == fy) & (src_df.get("fiscal_period", pd.Series()) == fp)]
                if not match.empty:
                    entry[label] = float(match.iloc[0]["val"])

            if rev != 0 and "operating_income" in entry:
                entry["operating_margin"] = round(entry["operating_income"] / rev, 4)

            results.append(entry)

        # Compute QoQ and YoY growth (results are newest-first)
        for i, entry in enumerate(results):
            if i + 1 < len(results) and results[i + 1].get("revenue", 0) != 0:
                entry["revenue_qoq_growth"] = round(
                    (entry["revenue"] - results[i + 1]["revenue"]) / abs(results[i + 1]["revenue"]), 4
                )
            if i + 4 < len(results) and results[i + 4].get("revenue", 0) != 0:
                entry["revenue_yoy_growth"] = round(
                    (entry["revenue"] - results[i + 4]["revenue"]) / abs(results[i + 4]["revenue"]), 4
                )
        return results

    def get_quarterly_summary_text(self, quarterly: Optional[List[Dict[str, Any]]] = None) -> str:
        """Format quarterly metrics into a compact text block."""
        if quarterly is None:
            quarterly = self.compute_quarterly_metrics()
        if not quarterly:
            return ""
        lines = ["=== Recent Quarterly Trends ==="]
        for q in quarterly:
            period = f"FY{q.get('fiscal_year', '?')} {q.get('fiscal_period', '?')}"
            rev_str = format_money(q.get("revenue"))
            parts = [f"  {period}: Rev {rev_str}"]
            if "operating_margin" in q:
                parts.append(f"OpMgn {q['operating_margin']*100:.1f}%")
            if "eps_diluted" in q:
                parts.append(f"EPS ${q['eps_diluted']:.2f}")
            if "revenue_qoq_growth" in q:
                parts.append(f"QoQ {q['revenue_qoq_growth']*100:+.1f}%")
            if "revenue_yoy_growth" in q:
                parts.append(f"YoY {q['revenue_yoy_growth']*100:+.1f}%")
            lines.append(" | ".join(parts))
        return "\n".join(lines)

    def to_summary_text(self, metrics: Optional[Dict[str, Any]] = None) -> str:
        """
        Produce a human-readable text summary of the financials
        suitable for inclusion in an LLM prompt.

        Args:
            metrics: Pre-computed metrics dict. If None, compute_metrics()
                     is called internally (kept for backward compatibility).
        """
        if metrics is None:
            metrics = self.compute_metrics()
        lines = [f"=== Financial Summary: {self.entity_name} ===\n"]

        def fmt(val: Any, is_dollars: bool = True, is_pct: bool = False) -> str:
            if val is None:
                return "N/A"
            if is_pct:
                return f"{val * 100:.1f}%"
            if is_dollars:
                return format_money(val)
            return str(val)

        lines.append("── Income Statement (Latest Annual) ──")
        lines.append(f"  Revenue:          {fmt(metrics.get('revenue'))}")
        lines.append(f"  Gross Profit:     {fmt(metrics.get('gross_profit'))}")
        lines.append(f"  Operating Income: {fmt(metrics.get('operating_income'))}")
        lines.append(f"  Net Income:       {fmt(metrics.get('net_income'))}")
        lines.append(f"  EPS (Diluted):    {fmt(metrics.get('eps_diluted'), is_dollars=False)}")
        lines.append(f"  Revenue Growth:   {fmt(metrics.get('revenue_growth_yoy'), is_pct=True)}")
        lines.append("")

        lines.append("── Margins ──")
        lines.append(f"  Gross Margin:     {fmt(metrics.get('gross_margin'), is_pct=True)}")
        lines.append(f"  Operating Margin: {fmt(metrics.get('operating_margin'), is_pct=True)}")
        lines.append(f"  Net Margin:       {fmt(metrics.get('net_margin'), is_pct=True)}")
        lines.append("")

        lines.append("── Balance Sheet ──")
        lines.append(f"  Total Assets:     {fmt(metrics.get('total_assets'))}")
        lines.append(f"  Total Liabilities:{fmt(metrics.get('total_liabilities'))}")
        lines.append(f"  Equity:           {fmt(metrics.get('stockholders_equity'))}")
        lines.append(f"  Cash:             {fmt(metrics.get('cash'))}")
        lines.append(f"  Long-Term Debt:   {fmt(metrics.get('long_term_debt'))}")
        lines.append("")

        lines.append("── Ratios ──")
        lines.append(f"  Debt/Equity:      {fmt(metrics.get('debt_to_equity'), is_dollars=False)}")
        lines.append(f"  ROE:              {fmt(metrics.get('roe'), is_pct=True)}")
        lines.append(f"  ROA:              {fmt(metrics.get('roa'), is_pct=True)}")
        lines.append("")

        lines.append("── Cash Flow ──")
        lines.append(f"  Operating CF:     {fmt(metrics.get('operating_cash_flow'))}")
        lines.append(f"  CapEx:            {fmt(metrics.get('capex'))}")
        lines.append(f"  Free Cash Flow:   {fmt(metrics.get('free_cash_flow'))}")
        lines.append("")

        lines.append(f"  Shares Out:       {fmt(metrics.get('shares_outstanding'), is_dollars=False)}")

        # Trend summary block
        lines.append("")
        lines.append("── Trends ──")
        lines.append(f"  Revenue CAGR (3Y): {fmt(metrics.get('revenue_cagr_3y'), is_pct=True)}")
        lines.append(f"  Revenue CAGR (5Y): {fmt(metrics.get('revenue_cagr_5y'), is_pct=True)}")
        lines.append(f"  Net Income CAGR (3Y): {fmt(metrics.get('net_income_cagr_3y'), is_pct=True)}")
        lines.append(f"  Net Income CAGR (5Y): {fmt(metrics.get('net_income_cagr_5y'), is_pct=True)}")
        ol = metrics.get("operating_leverage_5y")
        lines.append(f"  Operating Leverage (5Y): {ol if ol is not None else 'N/A'}")

        margins = self.get_historical_margins(years=5)
        if margins:
            gm_vals = [m["gross_margin"] for m in margins if "gross_margin" in m]
            om_vals = [m["operating_margin"] for m in margins if "operating_margin" in m]
            if len(gm_vals) >= 2:
                direction = "expanding" if gm_vals[0] > gm_vals[-1] else ("contracting" if gm_vals[0] < gm_vals[-1] else "stable")
                lines.append(f"  Gross Margin Direction (5Y): {direction}")
            if len(om_vals) >= 2:
                direction = "expanding" if om_vals[0] > om_vals[-1] else ("contracting" if om_vals[0] < om_vals[-1] else "stable")
                lines.append(f"  Operating Margin Direction (5Y): {direction}")

        return "\n".join(lines)

    def get_historical_revenue(self, years: int = 5) -> List[Dict[str, Any]]:
        """Return a list of {year, revenue} dicts for historical trend analysis."""
        for concept in [
            "Revenues",
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "SalesRevenueNet",
        ]:
            df = self._extract_concept(concept, form_filter=["10-K"])
            if not df.empty:
                rows = []
                for _, row in df.head(years).iterrows():
                    rows.append(
                        {
                            "period_end": str(row["end"].date()) if pd.notna(row["end"]) else None,
                            "fiscal_year": row.get("fiscal_year"),
                            "revenue": float(row["val"]),
                        }
                    )
                return rows
        return []

    def get_historical_net_income(self, years: int = 5) -> List[Dict[str, Any]]:
        """Return a list of {year, net_income} dicts."""
        df = self._extract_concept("NetIncomeLoss", form_filter=["10-K"])
        if df.empty:
            return []
        rows = []
        for _, row in df.head(years).iterrows():
            rows.append(
                {
                    "period_end": str(row["end"].date()) if pd.notna(row["end"]) else None,
                    "fiscal_year": row.get("fiscal_year"),
                    "net_income": float(row["val"]),
                }
            )
        return rows

    def supplement_with_edgartools(self, ticker: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Use edgartools financials to fill gaps in the XBRL-parsed metrics.
        Adds segment data, geographic breakdown, and any missing line items.
        Returns the augmented metrics dict; never removes existing values.
        """
        try:
            from edgar import Company

            company = Company(ticker.upper())
            if company.not_found:
                return metrics

            financials = company.get_financials()
            if financials is None:
                return metrics

            supplemented = dict(metrics)

            # Try to get segment/geographic data as summary text
            try:
                income = financials.income_statement()
                if income is not None:
                    df = income.to_dataframe()
                    if df is not None and not df.empty:
                        # Fill any missing core metrics from edgartools
                        label_map = {
                            "Revenue": "revenue",
                            "Net Income": "net_income",
                            "Gross Profit": "gross_profit",
                            "Operating Income": "operating_income",
                        }
                        for label, key in label_map.items():
                            if supplemented.get(key) is None:
                                for col_label in df.index:
                                    if label.lower() in str(col_label).lower():
                                        val = df.iloc[df.index.get_loc(col_label), 0]
                                        if pd.notna(val):
                                            supplemented[key] = float(val)
                                        break
            except Exception:
                pass

            # Segment data (if available via edgartools financials detailed view)
            try:
                detailed = financials.income_statement(view="detailed")
                if detailed is not None:
                    df_det = detailed.to_dataframe()
                    if df_det is not None and not df_det.empty:
                        segment_keywords = ["segment", "geographic", "region", "product line"]
                        segment_lines = []
                        for idx_label in df_det.index:
                            label_lower = str(idx_label).lower()
                            if any(kw in label_lower for kw in segment_keywords):
                                val = df_det.iloc[df_det.index.get_loc(idx_label), 0]
                                if pd.notna(val):
                                    segment_lines.append(f"  {idx_label}: {format_money(float(val))}")
                        if segment_lines:
                            supplemented["_segment_data"] = "\n".join(segment_lines)
            except Exception:
                pass

            return supplemented
        except Exception:
            return metrics
