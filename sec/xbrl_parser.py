"""
XBRL data parser for SEC company facts.

Transforms raw XBRL JSON from the SEC API into structured
DataFrames and computed financial metrics that agents consume.
"""

from typing import Any, Dict, List, Optional

import pandas as pd


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

        # Revenue growth (YoY)
        revenue_df = self._extract_concept("Revenues", form_filter=["10-K"])
        if revenue_df.empty:
            revenue_df = self._extract_concept(
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                form_filter=["10-K"],
            )
        if len(revenue_df) >= 2:
            latest = float(revenue_df.iloc[0]["val"])
            prior = float(revenue_df.iloc[1]["val"])
            if prior != 0:
                metrics["revenue_growth_yoy"] = round((latest - prior) / prior, 4)

        return metrics

    def to_summary_text(self) -> str:
        """
        Produce a human-readable text summary of the financials
        suitable for inclusion in an LLM prompt.
        """
        metrics = self.compute_metrics()
        lines = [f"=== Financial Summary: {self.entity_name} ===\n"]

        def fmt(val: Any, is_dollars: bool = True, is_pct: bool = False) -> str:
            if val is None:
                return "N/A"
            if is_pct:
                return f"{val * 100:.1f}%"
            if is_dollars and isinstance(val, (int, float)):
                if abs(val) >= 1e9:
                    return f"${val / 1e9:.2f}B"
                if abs(val) >= 1e6:
                    return f"${val / 1e6:.1f}M"
                return f"${val:,.0f}"
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
