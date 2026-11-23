# Enterprise ERP Ledgers & Audit CAATs Dataset Pack (2026)

## Contents Overview
1. **audit_examples/** (4 CSV files)
   - Industry-standard audit procedures mapped to ISA/IFRS standards, CAATs analytics rules, and sample findings across O2C, P2P, R2R, and Inventory/Assets/Tax.
2. **ledgers/** (6 ERP Systems x 6 Complete Ledgers = 36 CSV files, 1,050 rows each = 37,800 total rows)
   - `01_SAP_S4HANA` (Tables: ACDOCA, BSEG/BSID/BSIK, ANLA/ANLC, MSEG, FEBEP)
   - `02_Oracle_NetSuite`
   - `03_Xero_Cloud`
   - `04_Sage_Intacct`
   - `05_Microsoft_Dynamics_365`
   - `06_QuickBooks_Online`
3. **Injected Audit Anomalies (Tagged in the final column `AUDIT_TAG` / `Audit_Tag` / `AuditTag` for ground-truth validation):**
   - `ANOMALY:WEEKEND_MANUAL_JE` (General Ledger - Sunday manual entries)
   - `ANOMALY:ROUND_SUM_OUTLIER` (General Ledger - Large round-sum accruals)
   - `ANOMALY:CUTOFF_ERR_2026` (Accounts Receivable - Jan 2027 deliveries recognized in Dec 2026)
   - `ANOMALY:DUP_AR_INV` (Accounts Receivable - Duplicate customer billings)
   - `ANOMALY:DUP_AP_INV` (Accounts Payable - Duplicate vendor invoices)
   - `ANOMALY:BENFORD_THRESHOLD_SPLIT` (Accounts Payable - Benford's Law spike just under ZAR 50,000 approval limit)
   - `ANOMALY:UNMATCHED_GRN_INV` (Accounts Payable - Invoices lacking PO references)
   - `ANOMALY:DEPR_OVER_COST` (Fixed Assets - Accumulated depreciation exceeding acquisition cost)
   - `ANOMALY:NEG_INV_QTY` (Inventory - Negative stock quantities)
   - `ANOMALY:UNRECONCILED_CASH_ITEM` (Cash/Bank - Stale reconciling bank items)
