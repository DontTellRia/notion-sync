import os
from pathlib import Path
import re

from dotenv import load_dotenv
from notion_client import Client


# ============================================================
# FINANCIAL SYNC
# CONTROLLED EXECUTION
# ============================================================

INCOME_DATA_SOURCE_ID = (
    "3b55f703-3f4a-8080-a01a-000b8e4b5953"
)

EXPENSES_DATA_SOURCE_ID = (
    "3b55f703-3f4a-80cb-ab63-000bd02357c2"
)

FINANCIAL_TRANSACTIONS_DATA_SOURCE_ID = (
    "3b85f703-3f4a-809d-851d-000befb081ec"
)


# ============================================================
# ENVIRONMENT
# ============================================================

script_folder = Path(__file__).resolve().parent
env_file = script_folder / ".env"

print("=" * 70)
print("FINANCIAL SYNC")
print("CONTROLLED EXECUTION")
print("=" * 70)

print(f"Script folder: {script_folder}")
print(f".env exists:  {env_file.exists()}")

load_dotenv(
    dotenv_path=env_file,
    override=False
)

token = os.getenv("NOTION_TOKEN")

if not token:
    print("ERROR: NOTION_TOKEN was not found.")
    raise SystemExit(1)

print("Token found: True")


# ============================================================
# NOTION
# ============================================================

notion = Client(auth=token)

try:
    notion.users.me()
    print("Connected to Notion API!")
except Exception as e:
    print("ERROR: Could not connect to Notion API.")
    print(f"{type(e).__name__}: {e}")
    raise SystemExit(1)


# ============================================================
# GENERAL HELPERS
# ============================================================

def query_all_pages(data_source_id):
    results = []
    cursor = None

    while True:

        kwargs = {
            "data_source_id": data_source_id
        }

        if cursor:
            kwargs["start_cursor"] = cursor

        response = notion.data_sources.query(**kwargs)

        results.extend(
            response.get("results", [])
        )

        if not response.get("has_more"):
            break

        cursor = response.get("next_cursor")

    return results


def is_usable_page(page):
    return not (
        page.get("archived", False)
        or page.get("in_trash", False)
    )


def get_title(properties, name):
    prop = properties.get(name)

    if not prop:
        return ""

    return "".join(
        item.get("plain_text", "")
        for item in prop.get("title", [])
    ).strip()


def get_relation_ids(properties, name):
    prop = properties.get(name)

    if not prop:
        return []

    return [
        item["id"]
        for item in prop.get("relation", [])
        if item.get("id")
    ]


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
        value = rollup.get("date")
        return value.get("start") if value else None

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
        return (
            status_value.get("name")
            if status_value else None
        )

    if value_type == "select":
        select_value = value.get("select")
        return (
            select_value.get("name")
            if select_value else None
        )

    if value_type == "rich_text":
        return "".join(
            item.get("plain_text", "")
            for item in value.get("rich_text", [])
        ).strip()

    if value_type == "title":
        return "".join(
            item.get("plain_text", "")
            for item in value.get("title", [])
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


def normalize_expense_name(name):
    """
    Converts:
        Kape
        Kape 02
        Kape 03
        Kape 04

    into the base name:
        Kape

    This lets the script recognize repeated expense names.
    """

    match = re.match(
        r"^(.*?)(?:\s+(\d{2}))?$",
        name.strip()
    )

    if not match:
        return name.strip()

    base = match.group(1).strip()

    return base


def expense_name_for_occurrence(base_name, occurrence):
    """
    First occurrence:
        Kape

    Second:
        Kape 02

    Third:
        Kape 03
    """

    if occurrence == 1:
        return base_name

    return f"{base_name} {occurrence:02d}"


def extract_booking_number(title):
    """
    Returns the numeric part of:
        Booking0001
        Booking0002
        etc.

    Returns None for anything else.
    """

    if not title:
        return None

    match = re.fullmatch(
        r"Booking(\d+)",
        title.strip()
    )

    if not match:
        return None

    return int(match.group(1))


# ============================================================
# SAFE PAGE RETRIEVAL
# ============================================================

def retrieve_page(page_id):
    try:
        return notion.pages.retrieve(
            page_id=page_id
        )
    except Exception:
        return None


# ============================================================
# READ DATA SOURCES
# ============================================================

print()
print("Reading Income data source...")

income_pages = query_all_pages(
    INCOME_DATA_SOURCE_ID
)

print(
    f"Income pages found: {len(income_pages)}"
)


print()
print("Reading Expenses data source...")

expense_pages = query_all_pages(
    EXPENSES_DATA_SOURCE_ID
)

print(
    f"Expense pages found: {len(expense_pages)}"
)


print()
print("Reading Financial Transactions data source...")

financial_pages = query_all_pages(
    FINANCIAL_TRANSACTIONS_DATA_SOURCE_ID
)

print(
    "Financial Transaction pages found: "
    f"{len(financial_pages)}"
)


# ============================================================
# INDEX EXISTING FINANCIAL TRANSACTIONS
# ============================================================

financial_by_id = {}
financial_by_title = {}

for page in financial_pages:

    if not is_usable_page(page):
        continue

    page_id = page["id"]

    properties = page.get(
        "properties",
        {}
    )

    transaction_name = get_title(
        properties,
        "Transaction"
    )

    financial_by_id[page_id] = page

    if transaction_name:
        financial_by_title[
            transaction_name
        ] = page_id


# ============================================================
# FIND NEXT INCOME BOOKING NUMBER
# ============================================================

highest_booking_number = 0

for page in financial_pages:

    if not is_usable_page(page):
        continue

    properties = page.get(
        "properties",
        {}
    )

    title = get_title(
        properties,
        "Transaction"
    )

    number = extract_booking_number(title)

    if number is not None:
        highest_booking_number = max(
            highest_booking_number,
            number
        )


next_booking_number = highest_booking_number + 1


# ============================================================
# EXPENSE NAME OCCURRENCE INDEX
# ============================================================

expense_name_counts = {}

for page in financial_pages:

    if not is_usable_page(page):
        continue

    properties = page.get(
        "properties",
        {}
    )

    transaction_name = get_title(
        properties,
        "Transaction"
    )

    if not transaction_name:
        continue

    base_name = normalize_expense_name(
        transaction_name
    )

    expense_name_counts.setdefault(
        base_name,
        []
    )

    expense_name_counts[
        base_name
    ].append(transaction_name)


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
# TRACK SOURCE LINKS SEEN DURING THIS RUN
# ============================================================

active_income_source_ids = set()
active_expense_source_ids = set()


# ============================================================
# INCOME
# ============================================================

print()
print("-" * 70)
print("EVALUATING INCOME RECORDS")
print("-" * 70)


for page in income_pages:

    page_id = page["id"]

    if not is_usable_page(page):

        print()
        print(
            f"Income page: {page_id}"
        )
        print(
            "-> IGNORE: archived or in trash"
        )

        income_ignore += 1
        continue


    properties = page.get(
        "properties",
        {}
    )

    transaction_id = get_title(
        properties,
        "Transaction ID"
    )

    booking_ids = get_relation_ids(
        properties,
        "Bookings"
    )

    existing_relations = get_relation_ids(
        properties,
        "Financial Transactions"
    )

    status = get_rollup_value(
        properties,
        "Status"
    )

    amount = get_rollup_value(
        properties,
        "Amount"
    )

    date = get_rollup_value(
        properties,
        "Date"
    )


    print()
    print(
        f"Income: "
        f"{transaction_id or '[NO TRANSACTION ID]'}"
    )

    print(
        f"Page ID: {page_id}"
    )

    print(
        f"Status: {status}"
    )

    print(
        f"Amount: {amount}"
    )

    print(
        f"Date: {date}"
    )

    print(
        f"Bookings: {len(booking_ids)}"
    )

    print(
        "Existing Financial Transactions: "
        f"{len(existing_relations)}"
    )


    # --------------------------------------------------------
    # ELIGIBILITY
    # --------------------------------------------------------

    if not transaction_id:

        print(
            "-> IGNORE: missing Transaction ID"
        )

        income_ignore += 1
        continue


    if not booking_ids:

        print(
            "-> IGNORE: no Booking relation"
        )

        income_ignore += 1
        continue


    if status != "Completed":

        print(
            "-> IGNORE: status is not Completed"
        )

        income_ignore += 1
        continue


    if amount is None:

        print(
            "-> IGNORE: Amount missing"
        )

        income_ignore += 1
        continue


    if date is None:

        print(
            "-> IGNORE: Date missing"
        )

        income_ignore += 1
        continue


    active_income_source_ids.add(
        page_id
    )


    # --------------------------------------------------------
    # FIND EXISTING TRANSACTION
    #
    # The source relation is the authoritative identity.
    # --------------------------------------------------------

    existing_id = None

    if existing_relations:

        existing_id = existing_relations[0]


    # --------------------------------------------------------
    # UPDATE EXISTING INCOME TRANSACTION
    # --------------------------------------------------------

    if existing_id:

        existing_page = financial_by_id.get(
            existing_id
        )

        existing_title = ""

        if existing_page:

            existing_title = get_title(
                existing_page.get(
                    "properties",
                    {}
                ),
                "Transaction"
            )

        # ----------------------------------------------------
        # Keep an existing Booking0000 if it already exists,
        # but correct old FT-style names to the proper
        # sequential Booking naming when necessary.
        # ----------------------------------------------------

        if existing_title.startswith(
            "FT-INCOME-"
        ):

            corrected_name = (
                f"Booking{highest_booking_number + 1:04d}"
            )

            highest_booking_number += 1

        elif existing_title:

            corrected_name = existing_title

        else:

            corrected_name = (
                f"Booking{highest_booking_number + 1:04d}"
            )

            highest_booking_number += 1


        print("-> UPDATE")

        print(
            f"Financial Transaction: {existing_id}"
        )

        if existing_title != corrected_name:

            print(
                f"Transaction name correction: "
                f"{existing_title or '[EMPTY]'} "
                f"-> {corrected_name}"
            )


        notion.pages.update(

            page_id=existing_id,

            properties={

                "Transaction": {
                    "title": [
                        {
                            "text": {
                                "content":
                                    corrected_name
                            }
                        }
                    ]
                },

                "Type": {
                    "select": {
                        "name": "Income"
                    }
                },

                "Amount": {
                    "number": amount
                },

                "Date": {
                    "date": {
                        "start": date
                    }
                },

                "Income": {
                    "relation": [
                        {
                            "id": page_id
                        }
                    ]
                },

                "Expenses": {
                    "relation": []
                }
            }
        )

        print(
            "-> UPDATE SUCCESS"
        )

        income_update += 1
        continue


    # --------------------------------------------------------
    # CREATE NEW INCOME TRANSACTION
    # --------------------------------------------------------

    transaction_name = (
        f"Booking{next_booking_number:04d}"
    )

    next_booking_number += 1

    highest_booking_number = max(
        highest_booking_number,
        next_booking_number - 1
    )


    print("-> CREATE")

    print(
        f"Transaction: {transaction_name}"
    )


    created = notion.pages.create(

        parent={
            "data_source_id":
                FINANCIAL_TRANSACTIONS_DATA_SOURCE_ID
        },

        properties={

            "Transaction": {
                "title": [
                    {
                        "text": {
                            "content":
                                transaction_name
                        }
                    }
                ]
            },

            "Type": {
                "select": {
                    "name": "Income"
                }
            },

            "Amount": {
                "number": amount
            },

            "Date": {
                "date": {
                    "start": date
                }
            },

            "Income": {
                "relation": [
                    {
                        "id": page_id
                    }
                ]
            },

            "Expenses": {
                "relation": []
            }
        }
    )


    print(
        "-> CREATE SUCCESS"
    )

    print(
        "Financial Transaction Page ID: "
        f"{created['id']}"
    )

    financial_by_id[
        created["id"]
    ] = created

    financial_by_title[
        transaction_name
    ] = created["id"]

    income_create += 1


# ============================================================
# EXPENSES
# ============================================================

print()
print("-" * 70)
print("EVALUATING EXPENSE RECORDS")
print("-" * 70)


for page in expense_pages:

    page_id = page["id"]

    if not is_usable_page(page):

        print()
        print(
            f"Expense page: {page_id}"
        )
        print(
            "-> IGNORE: archived or in trash"
        )

        expense_ignore += 1
        continue


    properties = page.get(
        "properties",
        {}
    )

    title = get_title(
        properties,
        "Title"
    )

    amount = get_number_property(
        properties,
        "Amount"
    )

    date = get_date_property(
        properties,
        "Date"
    )

    existing_relations = get_relation_ids(
        properties,
        "Financial Transactions"
    )


    print()
    print(
        f"Expense: "
        f"{title or '[NO TITLE]'}"
    )

    print(
        f"Page ID: {page_id}"
    )

    print(
        f"Amount: {amount}"
    )

    print(
        f"Date: {date}"
    )

    print(
        "Existing Financial Transactions: "
        f"{len(existing_relations)}"
    )


    # --------------------------------------------------------
    # ELIGIBILITY
    # --------------------------------------------------------

    if not title:

        print(
            "-> IGNORE: missing Title"
        )

        expense_ignore += 1
        continue


    if amount is None:

        print(
            "-> IGNORE: Amount missing"
        )

        expense_ignore += 1
        continue


    if date is None:

        print(
            "-> IGNORE: Date missing"
        )

        expense_ignore += 1
        continue


    active_expense_source_ids.add(
        page_id
    )


    # --------------------------------------------------------
    # UPDATE EXISTING EXPENSE TRANSACTION
    # --------------------------------------------------------

    if existing_relations:

        existing_id = existing_relations[0]

        existing_page = financial_by_id.get(
            existing_id
        )

        existing_title = ""

        if existing_page:

            existing_title = get_title(
                existing_page.get(
                    "properties",
                    {}
                ),
                "Transaction"
            )


        # ----------------------------------------------------
        # Determine the correct Expense name.
        #
        # If the existing transaction is already properly
        # named, preserve it.
        #
        # If it is an old FT-style transaction, convert it
        # to the source Expense name.
        # ----------------------------------------------------

        if existing_title.startswith(
            "FT-EXPENSE-"
        ):

            base_name = title

            used_names = set(
                financial_by_title.keys()
            )

            if base_name not in used_names:

                corrected_name = base_name

            else:

                occurrence = 2

                while (
                    expense_name_for_occurrence(
                        base_name,
                        occurrence
                    )
                    in used_names
                ):
                    occurrence += 1

                corrected_name = (
                    expense_name_for_occurrence(
                        base_name,
                        occurrence
                    )
                )

        else:

            corrected_name = existing_title or title


        print("-> UPDATE")

        print(
            f"Financial Transaction: {existing_id}"
        )

        if existing_title != corrected_name:

            print(
                f"Transaction name correction: "
                f"{existing_title or '[EMPTY]'} "
                f"-> {corrected_name}"
            )


        notion.pages.update(

            page_id=existing_id,

            properties={

                "Transaction": {
                    "title": [
                        {
                            "text": {
                                "content":
                                    corrected_name
                            }
                        }
                    ]
                },

                "Type": {
                    "select": {
                        "name": "Expense"
                    }
                },

                "Amount": {
                    "number": amount
                },

                "Date": {
                    "date": {
                        "start": date
                    }
                },

                "Income": {
                    "relation": []
                },

                "Expenses": {
                    "relation": [
                        {
                            "id": page_id
                        }
                    ]
                }
            }
        )


        print(
            "-> UPDATE SUCCESS"
        )

        expense_update += 1
        continue


    # --------------------------------------------------------
    # CREATE NEW EXPENSE TRANSACTION
    # --------------------------------------------------------

    base_name = title.strip()

    used_names = set(
        financial_by_title.keys()
    )

    if base_name not in used_names:

        transaction_name = base_name

    else:

        occurrence = 2

        while (
            expense_name_for_occurrence(
                base_name,
                occurrence
            )
            in used_names
        ):
            occurrence += 1

        transaction_name = (
            expense_name_for_occurrence(
                base_name,
                occurrence
            )
        )


    print("-> CREATE")

    print(
        f"Transaction: {transaction_name}"
    )


    created = notion.pages.create(

        parent={
            "data_source_id":
                FINANCIAL_TRANSACTIONS_DATA_SOURCE_ID
        },

        properties={

            "Transaction": {
                "title": [
                    {
                        "text": {
                            "content":
                                transaction_name
                        }
                    }
                ]
            },

            "Type": {
                "select": {
                    "name": "Expense"
                }
            },

            "Amount": {
                "number": amount
            },

            "Date": {
                "date": {
                    "start": date
                }
            },

            "Income": {
                "relation": []
            },

            "Expenses": {
                "relation": [
                    {
                        "id": page_id
                    }
                ]
            }
        }
    )


    print(
        "-> CREATE SUCCESS"
    )

    print(
        "Financial Transaction Page ID: "
        f"{created['id']}"
    )

    financial_by_id[
        created["id"]
    ] = created

    financial_by_title[
        transaction_name
    ] = created["id"]

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

    properties = page.get(
        "properties",
        {}
    )

    transaction_name = get_title(
        properties,
        "Transaction"
    )

    income_relations = get_relation_ids(
        properties,
        "Income"
    )

    expense_relations = get_relation_ids(
        properties,
        "Expenses"
    )


    # --------------------------------------------------------
    # Income transaction
    # --------------------------------------------------------

    if income_relations:

        source_id = income_relations[0]

        source_page = retrieve_page(
            source_id
        )

        if source_page is None:

            print()
            print(
                f"Financial Transaction: "
                f"{transaction_name}"
            )

            print(
                f"Page ID: {page_id}"
            )

            print(
                "-> ORPHANED: Income source no longer exists"
            )

            notion.pages.update(
                page_id=page_id,
                archived=True
            )

            print(
                "-> FINANCIAL TRANSACTION ARCHIVED"
            )

            ledger_cleanup += 1

            continue


        if not is_usable_page(source_page):

            print()
            print(
                f"Financial Transaction: "
                f"{transaction_name}"
            )

            print(
                "-> SOURCE IS ARCHIVED OR IN TRASH"
            )

            notion.pages.update(
                page_id=page_id,
                archived=True
            )

            print(
                "-> FINANCIAL TRANSACTION ARCHIVED"
            )

            ledger_cleanup += 1

            continue


    # --------------------------------------------------------
    # Expense transaction
    # --------------------------------------------------------

    if expense_relations:

        source_id = expense_relations[0]

        source_page = retrieve_page(
            source_id
        )

        if source_page is None:

            print()
            print(
                f"Financial Transaction: "
                f"{transaction_name}"
            )

            print(
                f"Page ID: {page_id}"
            )

            print(
                "-> ORPHANED: Expense source no longer exists"
            )

            notion.pages.update(
                page_id=page_id,
                archived=True
            )

            print(
                "-> FINANCIAL TRANSACTION ARCHIVED"
            )

            ledger_cleanup += 1

            continue


        if not is_usable_page(source_page):

            print()
            print(
                f"Financial Transaction: "
                f"{transaction_name}"
            )

            print(
                "-> SOURCE IS ARCHIVED OR IN TRASH"
            )

            notion.pages.update(
                page_id=page_id,
                archived=True
            )

            print(
                "-> FINANCIAL TRANSACTION ARCHIVED"
            )

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

print(
    f"CREATE: {income_create}"
)

print(
    f"UPDATE: {income_update}"
)

print(
    f"IGNORE: {income_ignore}"
)

print()
print("EXPENSES")

print(
    f"CREATE: {expense_create}"
)

print(
    f"UPDATE: {expense_update}"
)

print(
    f"IGNORE: {expense_ignore}"
)

print()
print(
    f"ORPHANED LEDGER CLEANUP: {ledger_cleanup}"
)

print()
print(
    "Source Income/Expense records were not directly modified "
    "by the normal synchronization process."
)

print(
    "Archived and trashed source pages are ignored."
)

print(
    "Financial Transactions are synchronized from their "
    "source relations."
)

print("=" * 70)