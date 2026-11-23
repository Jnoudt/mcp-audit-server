"""Canonical ledger identification and source-column mappings."""

from __future__ import annotations

import re
from enum import StrEnum

import pandas as pd


class LedgerType(StrEnum):
    GENERAL_LEDGER = "general_ledger"
    ACCOUNTS_RECEIVABLE = "accounts_receivable"
    ACCOUNTS_PAYABLE = "accounts_payable"
    FIXED_ASSETS = "fixed_assets"
    INVENTORY = "inventory"
    CASH_BANK = "cash_bank"


def normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


COLUMN_ALIASES: dict[LedgerType, dict[str, tuple[str, ...]]] = {
    LedgerType.GENERAL_LEDGER: {
        "company_code": ("BUKRS", "Subsidiary", "Organisation", "ENTITY_ID", "DataAreaId", "Company"),
        "document_number": ("BELNR", "Internal_ID", "Journal_ID", "BATCH_NO", "Voucher", "TxnID"),
        "fiscal_year": ("GJAHR", "Fiscal_Year", "Financial_Year", "FISCAL_YR", "FiscalYear", "Tax_Year"),
        "document_type": ("BLART", "Type", "Source_Type", "JOURNAL_SYMBOL", "JournalCategory", "Txn_Type"),
        "posting_date": ("BUDAT", "Date", "Journal_Date", "WHEN_POSTED", "TransDate", "Txn_Date"),
        "account_code": ("RACCT", "Account", "Account_Code", "ACCOUNTNO", "MainAccountId", "Account_Num"),
        "cost_center": ("RCNTR", "Department", "Tracking_Category", "DEPT_ID", "CostCenter", "Class_Name"),
        "direction": ("SHKZG", "Dr_Cr", "Line_Type", "TR_TYPE", "IsCredit", "Posting_Type"),
        "amount": ("HSL", "Amount_ZAR", "Net_Amount", "AMOUNT", "AccountingCurrencyAmount", "Amount"),
        "currency": ("WAERS", "Currency", "CurrencyCode"),
        "description": ("SGTXT", "Memo", "Description", "DESCRIPTION", "Txt", "Line_Desc"),
    },
    LedgerType.ACCOUNTS_RECEIVABLE: {
        "company_code": ("BUKRS", "Subsidiary", "Organisation", "ENTITY_ID", "DataAreaId", "Company"),
        "customer_id": ("KUNNR", "Customer_ID", "Contact_Code", "CUSTOMERID", "AccountNum", "Customer_Ref"),
        "transaction_id": ("BELNR", "Tran_ID", "Invoice_ID", "RECORDNO", "Voucher", "TxnID"),
        "invoice_number": ("XBLNR", "Invoice_Num", "Invoice_Number", "DOCNUMBER", "InvoiceId", "Doc_Number"),
        "invoice_date": ("BLDAT", "Tran_Date", "Invoice_Date", "WHENCREATED", "InvoiceDate", "Txn_Date"),
        "posting_date": ("BUDAT", "Post_Date", "Post_Date", "WHENPOSTED", "PostingDate"),
        "due_date": ("ZFBDT", "Due_Date", "Due_Date", "WHENDUE", "DueDate"),
        "amount": ("DMBTR", "Gross_Amount", "Total_ZAR", "TOTALENTERED", "InvoiceAmount", "Total_Amt"),
        "currency": ("WAERS", "Currency", "CurrencyCode"),
        "tax_code": ("MWSKZ", "Tax_Code", "Tax_Rate", "TAXSOLUTIONID", "TaxGroup"),
    },
    LedgerType.ACCOUNTS_PAYABLE: {
        "company_code": ("BUKRS", "Subsidiary", "Organisation", "ENTITY_ID", "DataAreaId", "Company"),
        "vendor_id": ("LIFNR", "Vendor_ID", "Supplier_Code", "VENDORID", "VendAccount", "Vendor_Ref"),
        "transaction_id": ("BELNR", "Bill_ID", "RECORDNO", "Voucher", "TxnID"),
        "invoice_number": ("XBLNR", "Vendor_Ref", "Reference", "VENDOR_INV_NO", "VendInvoiceId", "Vendor_Doc_No"),
        "invoice_date": ("BLDAT", "Bill_Date", "Bill_Date", "WHENCREATED", "DocumentDate", "Txn_Date"),
        "posting_date": ("BUDAT", "Post_Date", "Post_Date", "WHENPOSTED", "TransDate"),
        "purchase_order": ("EBELN", "PO_Number", "PO_Ref", "PONUMBER", "PurchId"),
        "amount": ("DMBTR", "Gross_Amount", "Total_ZAR", "TOTALENTERED", "InvoiceAmount", "Total_Amt"),
        "currency": ("WAERS", "Currency", "CurrencyCode"),
        "tax_code": ("MWSKZ", "Tax_Code", "Tax_Rate", "TAXSOLUTIONID", "TaxGroup"),
    },
    LedgerType.FIXED_ASSETS: {
        "company_code": ("BUKRS", "Subsidiary", "Organisation", "ENTITY_ID", "DataAreaId", "Company"),
        "asset_id": ("ANLN1", "Asset_ID", "Asset_Number", "ASSETID", "AssetId", "Fixed_Asset_ID"),
        "asset_class": ("ANLKL", "Asset_Type", "Asset_Pool", "CLASSID", "AssetGroup", "Category"),
        "description": ("TXT50", "Asset_Name", "Description", "ASSETNAME", "Name", "Asset_Description"),
        "in_service_date": ("AKTIV", "Depr_Start", "Purchase_Date", "IN_SERVICE_DATE", "AcquisitionDate", "Date_Acquired"),
        "useful_life_years": ("NDJAR", "Useful_Life_Yrs", "Life_Years", "LIFE_YRS", "ServiceLife", "Useful_Life"),
        "acquisition_cost": ("ANSWL", "Original_Cost", "Purchase_Price", "ACQ_COST", "AcquisitionPrice", "Cost_Basis"),
        "accumulated_depreciation": ("KNAFA", "Accum_Depr", "Accumulated_Dep", "ACCUM_DEPR", "DepreciationAccum", "Accum_Depreciation"),
        "period_depreciation": ("NAFAG", "Current_Depr", "Monthly_Dep", "PERIOD_DEPR", "DepreciationPeriod", "Expense_Amt"),
        "currency": ("WAERS", "Currency", "CurrencyCode"),
    },
    LedgerType.INVENTORY: {
        "location": ("WERKS", "Location", "Warehouse", "WAREHOUSEID", "InventSiteId", "Site_Name"),
        "item_id": ("MATNR", "Item_SKU", "Item_Code", "ITEMID", "ItemId", "SKU"),
        "description": ("MAKTX", "Item_Name", "Description", "ITEMDESC", "ItemName", "Product_Service"),
        "movement_type": ("BWART", "Trans_Type", "Movement_Type", "DOC_TYPE", "ReferenceCategory", "Adjustment_Type"),
        "reference_number": ("MBLNR", "Doc_Number", "Reference_No", "DOCID", "Voucher", "Ref_No"),
        "posting_date": ("BUDAT", "Date", "Date", "TRANS_DATE", "DateFinancial", "Txn_Date"),
        "quantity": ("MENGE", "Quantity", "Qty_Change", "QTY", "Qty", "Qty_On_Hand_Diff"),
        "unit_of_measure": ("MEINS", "UOM", "Unit", "UNIT", "UnitId", "UOM"),
        "unit_cost": ("VERPR", "Unit_Cost", "Cost_Price", "UNITCOST", "CostPrice", "Avg_Cost"),
        "total_cost": ("DMBTR", "Total_Value", "Total_Cost", "EXTENDED_COST", "CostAmountPosted", "Asset_Value_Change"),
    },
    LedgerType.CASH_BANK: {
        "company_code": ("BUKRS", "Subsidiary", "Organisation", "ENTITY_ID", "DataAreaId", "Company"),
        "bank_account": ("HBKID", "Bank_Account", "Bank_Name", "BANKACCOUNTID", "BankAccountId"),
        "account_identifier": ("HKTID", "Account_Num", "Bank_Acct_No", "ACCT_NO", "IBAN_Local", "Routing_Acct"),
        "transaction_id": ("BELNR", "Payment_ID", "Statement_ID", "PAYMENT_KEY", "BankTransId", "Deposit_Check_ID"),
        "value_date": ("VALUT", "Value_Date", "Bank_Date", "CLEARED_DATE", "TransDate", "Cleared_Date"),
        "posting_date": ("BUDAT", "Post_Date", "Reconciled_Date", "POST_DATE", "AckDate", "Txn_Date"),
        "payment_type": ("ZLSCH", "Pay_Method", "Payment_Type", "PAYMETHOD", "PaymMode", "Payment_Method"),
        "amount": ("WRBTR", "Amount", "Amount_ZAR", "TRX_AMOUNT", "AmountCur", "Amount"),
        "currency": ("WAERS", "Currency", "CurrencyCode"),
        "reference": ("SGTXT", "Memo", "Reference", "MEMO", "Txt", "Memo"),
    },
}

_REQUIRED_FIELDS: dict[LedgerType, tuple[str, ...]] = {
    LedgerType.GENERAL_LEDGER: ("document_number", "posting_date", "account_code", "amount"),
    LedgerType.ACCOUNTS_RECEIVABLE: ("customer_id", "invoice_number", "invoice_date", "amount"),
    LedgerType.ACCOUNTS_PAYABLE: ("vendor_id", "invoice_number", "invoice_date", "amount"),
    LedgerType.FIXED_ASSETS: ("asset_id", "acquisition_cost", "accumulated_depreciation"),
    LedgerType.INVENTORY: ("item_id", "movement_type", "posting_date", "quantity"),
    LedgerType.CASH_BANK: ("bank_account", "transaction_id", "value_date", "amount"),
}


def identify_ledger_type(columns: list[str] | pd.Index) -> LedgerType:
    """Classify a ledger using known column aliases; never use row labels."""
    headers = {normalize_header(str(column)) for column in columns}
    candidates: list[tuple[int, LedgerType]] = []
    for ledger_type, mapping in COLUMN_ALIASES.items():
        present = {
            canonical
            for canonical, aliases in mapping.items()
            if any(normalize_header(alias) in headers for alias in aliases)
        }
        required = set(_REQUIRED_FIELDS[ledger_type])
        score = len(present & required)
        if required.issubset(present):
            candidates.append((score, ledger_type))
    if len(candidates) != 1:
        raise ValueError("Ledger type is ambiguous or unsupported; provide an explicit reviewed mapping.")
    return candidates[0][1]


def canonical_column_map(ledger_type: LedgerType, columns: list[str] | pd.Index) -> dict[str, str]:
    headers = {normalize_header(str(column)): str(column) for column in columns}
    mapping: dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES[ledger_type].items():
        for alias in aliases:
            source = headers.get(normalize_header(alias))
            if source:
                mapping[canonical] = source
                break
    missing = set(_REQUIRED_FIELDS[ledger_type]) - set(mapping)
    if missing:
        raise ValueError(f"Required ledger columns are missing: {', '.join(sorted(missing))}.")
    return mapping
