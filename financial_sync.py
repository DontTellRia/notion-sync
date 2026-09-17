import os
import re
from pathlib import Path

from dotenv import load_dotenv
from notion_client import Client


# ============================================================
# FINANCIAL SYNC - SAFETY COPY
# ============================================================

INCOME_DATA_SOURCE_ID = "c8dbc29d-4662-83e2-bcc5-078c6cca768f"
EXPENSES_DATA_SOURCE_ID = "413bc29d-4662-8370-bae0-87377498be94"
FINANCIAL_TRANSACTIONS_DATA_SOURCE_ID = "5ccbc29d-4662-83b1-b274-07583f086384"

PREVIEW_MODE = False

script_folder = Path(__file__).resolve().parent
env_file = script_folder / ".env"

print("=" * 70)
print("FINANCIAL SYNC - SAFETY COPY")
print("=" * 70)

print(f"Script folder: {script_folder}")
print(f".env exists:  {env_file.exists()}")

load_dotenv(dotenv_path=env_file, override=False)

token = os.getenv("NOTION_TOKEN", "").strip()
if not token:
    print("ERROR: NOTION_TOKEN was not found.")
    raise SystemExit(1)

print("Token found: True")

notion = Client(auth=token)

try:
    notion.users.me()
    print("Connected to Notion API!")
except Exception as exc:
    print("ERROR: Could not connect to Notion API.")
    print(f"{type(exc).__name__}: {exc}")
    raise SystemExit(1)


# ============================================================
# GENERAL HELPERS
# ============================================================


def query_all_pages(data_source_id):
    results = []
    cursor = None

    while True:
        kwargs = {"data_source_id": data_source_id}
        if cursor:
            kwargs["start_cursor"] = cursor

        response = notion.data_sources.query(**kwargs)
        results.extend(response.get("results", []))

        if not response.get("has_more"):
            break

        cursor = response.get("next_cursor")

    return results


def is_usable_page(page):
    return not (page.get("archived", False) or page.get("in_trash", False))


def get_title(properties, name):
    prop = properties.get(name)
    if not prop:
        return ""

    return "".join(
        item.get("plain_text", "") for item in prop.get("title", [])
    ).strip()


def get_relation_ids(properties, *names):
    all_ids = []
    for name in names:
        prop = properties.get(name)
        if not prop:
            continue
        for item in prop.get("relation", []):
            item_id = item.get("id")
            if item_id and item_id not in all_ids:
                all_ids.append(item_id)
    return all_ids


def get_first_relation_id(properties, *names):
    ids = get_relation_ids(properties, *names)
    return ids[0] if ids else None


def get_rollup_value(properties, name):
    prop = properties.get(name)
    if not prop:
        return None

    rollup = prop.get("rollup")
    if not rollup:
        return None

    rollup_type = rollup.get("type")
    if rollup_type == "number":
        return rollup.get("number")
    if rollup_type == "date":
        date_value = rollup.get("date")
        return date_value.get("start") if date_value else None
    if rollup_type != "array":
        return None

    values = rollup.get("array", [])
    if not values:
        return None

    value = values[0]
    value_type = value.get("type")
    if value_type == "number":
        return value.get("number")
    if value_type == "date":
        date_value = value.get("date")
        return date_value.get("start") if date_value else None
    if value_type == "status":
        status_value = value.get("status")
        return status_value.get("name") if status_value else None
    if value_type == "select":
        select_value = value.get("select")
        return select_value.get("name") if select_value else None
    if value_type == "rich_text":
        return "".join(
            item.get("plain_text", "") for item in value.get("rich_text", [])
        ).strip()
    if value_type == "title":
        return "".join(
            item.get("plain_text", "") for item in value.get("title", [])
        ).strip()
    return None


def get_number_property(properties, name):
    prop = properties.get(name)
    if not prop:
        return None
    return prop.get("number")


def get_date_property(properties, name):
    prop = properties.get(name)
    if not prop:
        return None
    value = prop.get("date")
    if not value:
        return None
    return value.get("start")


def retrieve_page(page_id):
    try:
        return notion.pages.retrieve(page_id=page_id)
    except Exception:
        return None


def find_existing_transaction_for_source(source_id, source_type):
    source_field = "Income" if source_type == "income" else "Expenses"

    for page in financial_pages:
        if not is_usable_page(page):
            continue

        if source_id in get_relation_ids(page.get("properties", {}), source_field):
            return page

    return None


def transaction_needs_update(existing_page, source_type, wanted_name, wanted_amount, wanted_date, source_id):
    props = existing_page.get("properties", {})
    existing_title = get_title(props, "Transaction")
    existing_amount = get_number_property(props, "Amount")
    existing_date = get_date_property(props, "Date")
    existing_type = props.get("Type", {}).get("select", {}).get("name")
    target_field = "Income" if source_type == "income" else "Expenses"
    existing_relations = get_relation_ids(props, target_field)

    if existing_title != wanted_name:
        return True
    if existing_amount != wanted_amount:
        return True
    if existing_date != wanted_date:
        return True
    if existing_type != ("Income" if source_type == "income" else "Expense"):
        return True
    if source_id not in existing_relations:
        return True

    return False


def normalize_expense_name(name):
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.strip())


def extract_booking_number(title):
    if not title:
        return None

    match = re.fullmatch(r"(?:BOOKING|Booking)\s*(\d+)", title.strip(), re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def extract_income_number(title):
    if not title:
        return None

    match = re.fullmatch(r"(?:INCOME|Income)\s*(\d+)", title.strip(), re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def extract_expense_sequence(title, base_name):
    if not title:
        return None

    cleaned = title.strip()
    if not cleaned:
        return None

    candidate = re.escape(base_name.strip())
    match = re.fullmatch(rf"{candidate}(\d+)", cleaned)
    if not match:
        return None

    return int(match.group(1))


def booking_title(number):
    return f"BOOKING {number:04d}"


def income_title(number):
    return f"INCOME {number:04d}"


def expense_title(base_name, occurrence):
    return f"{base_name}{occurrence:03d}"


def has_schedule_relation(properties):
    for name in ("Schedules", "Schedule", "Schedule(s)", "Client Schedule"):
        if properties.get(name):
            rels = properties.get(name, {}).get("relation", [])
            if rels:
                return True
    return False


def next_unique_expense_name(base_name, used_names):
    base_name = base_name.strip()
    if not base_name:
        return "Expense001"

    occurrence = 1
    while True:
        candidate = expense_title(base_name, occurrence)
        if candidate not in used_names:
            return candidate
        occurrence += 1


def next_unique_income_name(prefix, used_names, next_counter):
    while True:
        candidate = f"{prefix} {next_counter:04d}"
        if candidate not in used_names:
            return candidate, next_counter + 1
        next_counter += 1


# ============================================================
# LOAD SOURCE DATA
# ============================================================

print()
print("Reading Income data source...")
income_pages = query_all_pages(INCOME_DATA_SOURCE_ID)
print(f"Income pages found: {len(income_pages)}")

print()
print("Reading Expenses data source...")
expense_pages = query_all_pages(EXPENSES_DATA_SOURCE_ID)
print(f"Expense pages found: {len(expense_pages)}")

print()
print("Reading Financial Transactions data source...")
financial_pages = query_all_pages(FINANCIAL_TRANSACTIONS_DATA_SOURCE_ID)
print(f"Financial Transaction pages found: {len(financial_pages)}")


# ============================================================
# BUILD INDEX OF FINANCIAL TRANSACTIONS
# ============================================================

financial_by_id = {}
financial_by_title = {}

for page in financial_pages:
    if not is_usable_page(page):
        continue

    page_id = page["id"]
    properties = page.get("properties", {})
    transaction_name = get_title(properties, "Transaction")

    financial_by_id[page_id] = page
    if transaction_name:
        financial_by_title[transaction_name] = page_id


# ============================================================
# TRACK HIGHER BOOKING / INCOME / EXPENSE COUNTERS
# ============================================================

highest_booking_number = 0
highest_income_number = 0

for page in financial_pages:
    if not is_usable_page(page):
        continue

    title = get_title(page.get("properties", {}), "Transaction")
    if not title:
        continue

    number = extract_booking_number(title)
    if number is not None:
        highest_booking_number = max(highest_booking_number, number)

    number = extract_income_number(title)
    if number is not None:
        highest_income_number = max(highest_income_number, number)

next_booking_number = highest_booking_number + 1
next_income_number = highest_income_number + 1


# ============================================================
# COUNTERS
# ============================================================

income_create = 0
income_update = 0
income_ignore = 0
expense_create = 0
expense_update = 0
expense_ignore = 0
ledger_cleanup = 0


# ============================================================
# SOURCE SETS FOR DELETION CHECKS
# ============================================================

active_income_source_ids = set()
active_expense_source_ids = set()

def record_source_id(source_id, source_type):
    if source_type == "income":
        active_income_source_ids.add(source_id)
    elif source_type == "expense":
        active_expense_source_ids.add(source_id)


# ============================================================
# INCOME PROCESSING
# ============================================================

print()
print("-" * 70)
print("EVALUATING INCOME RECORDS")
print("-" * 70)

for page in income_pages:
    page_id = page["id"]

    if not is_usable_page(page):
        print()
        print(f"Income page: {page_id}")
        print("-> IGNORE: archived or in trash")
        income_ignore += 1
        continue

    properties = page.get("properties", {})
    transaction_id = get_title(properties, "Transaction ID")
    booking_ids = get_relation_ids(properties, "Bookings", "Booking")
    existing_relations = get_relation_ids(properties, "Financial Transactions")
    status = get_rollup_value(properties, "Status")
    amount = get_rollup_value(properties, "Amount")
    date = get_rollup_value(properties, "Date")
    has_schedule = has_schedule_relation(properties)

    print()
    print(f"Income: {transaction_id or '[NO TRANSACTION ID]'}")
    print(f"Page ID: {page_id}")
    print(f"Status: {status}")
    print(f"Amount: {amount}")
    print(f"Date: {date}")
    print(f"Bookings: {len(booking_ids)}")
    print(f"Schedule relation: {has_schedule}")
    print(f"Existing Financial Transactions: {len(existing_relations)}")

    if not transaction_id:
        print("-> IGNORE: missing Transaction ID")
        income_ignore += 1
        continue

    if has_schedule:
        print("-> IGNORE: source has a schedule relation; schedule DB is excluded for privacy")
        income_ignore += 1
        continue

    if status != "Completed":
        print("-> IGNORE: status is not Completed")
        income_ignore += 1
        continue

    if amount is None:
        print("-> IGNORE: Amount missing")
        income_ignore += 1
        continue

    if date is None:
        print("-> IGNORE: Date missing")
        income_ignore += 1
        continue

    record_source_id(page_id, "income")

    has_booking_relation = bool(booking_ids)
    existing_id = existing_relations[0] if existing_relations else None
    if not existing_id:
        matching_page = find_existing_transaction_for_source(page_id, "income")
        if matching_page:
            existing_id = matching_page["id"]

    if existing_id:
        existing_page = financial_by_id.get(existing_id)
        if existing_page is None:
            existing_page = retrieve_page(existing_id)

        existing_title = ""
        if existing_page:
            existing_title = get_title(existing_page.get("properties", {}), "Transaction")

        if has_booking_relation:
            corrected_name = booking_title(next_booking_number) if not existing_title.startswith("BOOKING") else existing_title
            if not existing_title.startswith("BOOKING"):
                next_booking_number += 1
        else:
            corrected_name = income_title(next_income_number) if not existing_title.startswith("INCOME") else existing_title
            if not existing_title.startswith("INCOME"):
                next_income_number += 1

        if existing_page and not transaction_needs_update(existing_page, "income", corrected_name, amount, date, page_id):
            print("-> NO CHANGE NEEDED")
            income_ignore += 1
            continue

        print("-> UPDATE")
        print(f"Financial Transaction: {existing_id}")
        if existing_title != corrected_name:
            print(f"Transaction name correction: {existing_title or '[EMPTY]'} -> {corrected_name}")

        notion.pages.update(
            page_id=existing_id,
            properties={
                "Transaction": {"title": [{"text": {"content": corrected_name}}]},
                "Type": {"select": {"name": "Income"}},
                "Amount": {"number": amount},
                "Date": {"date": {"start": date}},
                "Income": {"relation": [{"id": page_id}]},
                "Expenses": {"relation": []},
            },
        )

        financial_by_id[existing_id] = notion.pages.retrieve(page_id=existing_id)
        financial_by_title[corrected_name] = existing_id
        income_update += 1
        continue

    if has_booking_relation:
        transaction_name = booking_title(next_booking_number)
        next_booking_number += 1
        highest_booking_number = max(highest_booking_number, next_booking_number - 1)
    else:
        transaction_name = income_title(next_income_number)
        next_income_number += 1
        highest_income_number = max(highest_income_number, next_income_number - 1)

    print("-> CREATE")
    print(f"Transaction: {transaction_name}")

    created = notion.pages.create(
        parent={"data_source_id": FINANCIAL_TRANSACTIONS_DATA_SOURCE_ID},
        properties={
            "Transaction": {"title": [{"text": {"content": transaction_name}}]},
            "Type": {"select": {"name": "Income"}},
            "Amount": {"number": amount},
            "Date": {"date": {"start": date}},
            "Income": {"relation": [{"id": page_id}]},
            "Expenses": {"relation": []},
        },
    )

    print("-> CREATE SUCCESS")
    print(f"Financial Transaction Page ID: {created['id']}")
    financial_by_id[created["id"]] = created
    financial_by_title[transaction_name] = created["id"]
    income_create += 1


# ============================================================
# EXPENSE PROCESSING
# ============================================================

print()
print("-" * 70)
print("EVALUATING EXPENSE RECORDS")
print("-" * 70)

for page in expense_pages:
    page_id = page["id"]

    if not is_usable_page(page):
        print()
        print(f"Expense page: {page_id}")
        print("-> IGNORE: archived or in trash")
        expense_ignore += 1
        continue

    properties = page.get("properties", {})
    title = get_title(properties, "Title")
    amount = get_number_property(properties, "Amount")
    date = get_date_property(properties, "Date")
    existing_relations = get_relation_ids(properties, "Financial Transactions")

    print()
    print(f"Expense: {title or '[NO TITLE]'}")
    print(f"Page ID: {page_id}")
    print(f"Amount: {amount}")
    print(f"Date: {date}")
    print(f"Existing Financial Transactions: {len(existing_relations)}")

    if not title:
        print("-> IGNORE: missing Title")
        expense_ignore += 1
        continue

    if amount is None:
        print("-> IGNORE: Amount missing")
        expense_ignore += 1
        continue

    if date is None:
        print("-> IGNORE: Date missing")
        expense_ignore += 1
        continue

    record_source_id(page_id, "expense")

    if not existing_relations:
        matching_page = find_existing_transaction_for_source(page_id, "expense")
        if matching_page:
            existing_relations = [matching_page["id"]]

    if existing_relations:
        existing_id = existing_relations[0]
        existing_page = financial_by_id.get(existing_id)
        if existing_page is None:
            existing_page = retrieve_page(existing_id)

        existing_title = ""
        if existing_page:
            existing_title = get_title(existing_page.get("properties", {}), "Transaction")

        base_name = normalize_expense_name(title)
        corrected_name = existing_title or base_name

        if existing_title.startswith("FT-EXPENSE-") or existing_title == "":
            corrected_name = next_unique_expense_name(base_name, set(financial_by_title.keys()))

        if existing_page and not transaction_needs_update(existing_page, "expense", corrected_name, amount, date, page_id):
            print("-> NO CHANGE NEEDED")
            expense_ignore += 1
            continue

        print("-> UPDATE")
        print(f"Financial Transaction: {existing_id}")
        if existing_title != corrected_name:
            print(f"Transaction name correction: {existing_title or '[EMPTY]'} -> {corrected_name}")

        notion.pages.update(
            page_id=existing_id,
            properties={
                "Transaction": {"title": [{"text": {"content": corrected_name}}]},
                "Type": {"select": {"name": "Expense"}},
                "Amount": {"number": amount},
                "Date": {"date": {"start": date}},
                "Income": {"relation": []},
                "Expenses": {"relation": [{"id": page_id}]},
            },
        )

        financial_by_id[existing_id] = notion.pages.retrieve(page_id=existing_id)
        financial_by_title[corrected_name] = existing_id
        expense_update += 1
        continue

    base_name = normalize_expense_name(title)
    transaction_name = next_unique_expense_name(base_name, set(financial_by_title.keys()))

    print("-> CREATE")
    print(f"Transaction: {transaction_name}")

    created = notion.pages.create(
        parent={"data_source_id": FINANCIAL_TRANSACTIONS_DATA_SOURCE_ID},
        properties={
            "Transaction": {"title": [{"text": {"content": transaction_name}}]},
            "Type": {"select": {"name": "Expense"}},
            "Amount": {"number": amount},
            "Date": {"date": {"start": date}},
            "Income": {"relation": []},
            "Expenses": {"relation": [{"id": page_id}]},
        },
    )

    print("-> CREATE SUCCESS")
    print(f"Financial Transaction Page ID: {created['id']}")
    financial_by_id[created["id"]] = created
    financial_by_title[transaction_name] = created["id"]
    expense_create += 1


# ============================================================
# ORPHAN / SOURCE-DELETION CLEANUP
# ============================================================

print()
print("-" * 70)
print("CHECKING FOR ORPHANED FINANCIAL TRANSACTIONS")
print("-" * 70)

for page in financial_pages:
    if not is_usable_page(page):
        continue

    page_id = page["id"]
    properties = page.get("properties", {})
    transaction_name = get_title(properties, "Transaction")
    income_relations = get_relation_ids(properties, "Income")
    expense_relations = get_relation_ids(properties, "Expenses")

    if income_relations:
        source_id = income_relations[0]
        source_page = retrieve_page(source_id)

        if source_page is None or not is_usable_page(source_page):
            print()
            print(f"Financial Transaction: {transaction_name}")
            print(f"Page ID: {page_id}")
            print("-> ORPHANED: Income source no longer exists or is trashed")
            notion.pages.update(page_id=page_id, archived=True)
            print("-> FINANCIAL TRANSACTION ARCHIVED")
            ledger_cleanup += 1
            continue

        if source_id not in active_income_source_ids:
            print()
            print(f"Financial Transaction: {transaction_name}")
            print(f"Page ID: {page_id}")
            print("-> ORPHANED: Income source was deleted from the source DB")
            notion.pages.update(page_id=page_id, archived=True)
            print("-> FINANCIAL TRANSACTION ARCHIVED")
            ledger_cleanup += 1
            continue

    if expense_relations:
        source_id = expense_relations[0]
        source_page = retrieve_page(source_id)

        if source_page is None or not is_usable_page(source_page):
            print()
            print(f"Financial Transaction: {transaction_name}")
            print(f"Page ID: {page_id}")
            print("-> ORPHANED: Expense source no longer exists or is trashed")
            notion.pages.update(page_id=page_id, archived=True)
            print("-> FINANCIAL TRANSACTION ARCHIVED")
            ledger_cleanup += 1
            continue

        if source_id not in active_expense_source_ids:
            print()
            print(f"Financial Transaction: {transaction_name}")
            print(f"Page ID: {page_id}")
            print("-> ORPHANED: Expense source was deleted from the source DB")
            notion.pages.update(page_id=page_id, archived=True)
            print("-> FINANCIAL TRANSACTION ARCHIVED")
            ledger_cleanup += 1
            continue


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 70)
print("EXECUTION COMPLETE")
print("=" * 70)

print()
print("INCOME")
print(f"CREATE: {income_create}")
print(f"UPDATE: {income_update}")
print(f"IGNORE: {income_ignore}")

print()
print("EXPENSES")
print(f"CREATE: {expense_create}")
print(f"UPDATE: {expense_update}")
print(f"IGNORE: {expense_ignore}")

print()
print(f"ORPHANED LEDGER CLEANUP: {ledger_cleanup}")

print()
print("Source Income/Expense records were not directly modified by the normal synchronization process.")
print("Archived and trashed source pages are ignored.")
print("Financial Transactions are synchronized from their source relations.")
print("=" * 70)
