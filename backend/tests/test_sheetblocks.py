"""Sheet app blocks: one sheet, several blocks of lines, one summary and one approval that
issues one receipt per block. Each line is marked Cash, Card or Split; the marks are only a
reference, the card machine slip decides the card total and is shared out between receipts."""
import uuid
from decimal import Decimal

from services.daysheet.service import allocate_card
from tests.conftest import stock_of

D = Decimal


def line(product: dict, qty: str, price: str, block: int = 1, pay: str = "cash", card: str | None = None) -> dict:
    return {
        "product_id": product["id"], "product": product["name"], "qty": qty, "price": price,
        "block": block, "pay": pay, "card": card,
    }


def body(lines: list[dict], blocks: int, card: str, counted: str) -> dict:
    return {"lang": "en", "content": {"blocks": blocks, "lines": lines, "expenses": [], "card": card, "counted": counted}}


async def waiting_id(client, code: str) -> int:
    return next(s["id"] for s in (await client.get("/daysheets?status=submitted")).json() if s["code"] == code)


# ── Sharing the slip between receipts ───────────────────────────

def test_no_marks_share_the_slip_by_receipt_total():
    assert allocate_card([(D("100"), D("0")), (D("50"), D("0"))], D("30")) == [D("20.00"), D("10.00")]


def test_marked_card_stays_with_its_block_and_the_rest_follows_cash():
    # 15 marked in block 1; the other 15 goes by what is left unmarked: 85 vs 50
    assert allocate_card([(D("100"), D("15")), (D("50"), D("0"))], D("30")) == [D("24.44"), D("5.56")]


def test_marks_above_the_slip_are_scaled_down_to_the_slip():
    assert allocate_card([(D("100"), D("40")), (D("50"), D("20"))], D("30")) == [D("20.00"), D("10.00")]


def test_shares_always_add_up_to_the_slip_and_never_pass_a_receipt():
    blocks = [(D("33.33"), D("0")), (D("33.33"), D("10")), (D("33.34"), D("0")), (D("0.01"), D("0"))]
    for slip in (D("0"), D("0.01"), D("0.03"), D("10"), D("57.77"), D("100.01")):
        shares = allocate_card(blocks, slip)
        assert sum(shares) == slip, slip
        assert all(D("0") <= s <= total for s, (total, _) in zip(shares, blocks)), (slip, shares)


# ── The whole flow ──────────────────────────────────────────────

async def test_two_blocks_one_approval_two_receipts(staff, make_product, client, shift):
    employee = await staff("sheet")
    rice, oil = await make_product(stock="10"), await make_product(stock="10")
    lines = [
        line(rice, "2", "10.00", block=1),
        line(oil, "1", "5.00", block=1, pay="card"),
        line(rice, "3", "10.00", block=2, pay="split", card="4.00"),
    ]
    # sales 25 + 30 = 55; slip 20 -> cash due 35
    sent = await employee.post(f"/daysheets/app/{uuid.uuid4()}/submit", json=body(lines, 2, card="20", counted="35"))
    assert sent.status_code == 200, sent.text
    assert D(sent.json()["totals"]["card_marked"]) == D("9.00")

    sheet_id = await waiting_id(client, sent.json()["code"])
    review = (await client.get(f"/daysheets/{sheet_id}/review")).json()
    assert review["can_approve"], review["problems"]
    assert [(b["block"], D(b["total"])) for b in review["blocks"]] == [(1, D("25.00")), (2, D("30.00"))]
    assert sum(D(b["card"]) for b in review["blocks"]) == D("20.00")
    assert D(review["totals"]["difference"]) == 0

    approved = await client.post(f"/daysheets/{sheet_id}/approve")
    assert approved.status_code == 200, approved.text
    result = approved.json()
    assert len(result["receipt_refs"]) == 2
    assert await stock_of(client, rice["id"]) == 5
    assert await stock_of(client, oil["id"]) == 9

    txns = {t["ref_number"]: t for t in (await client.get("/transactions?limit=10")).json()}
    receipts = [txns[ref] for ref in result["receipt_refs"]]
    assert [D(str(t["total_amount"])) for t in receipts] == [D("25.00"), D("30.00")]
    assert sum(D(str(t["payment_card"])) for t in receipts) == D("20.00")
    for t, b in zip(receipts, result["blocks"]):
        assert t["shift_id"] == shift["id"]
        assert D(str(t["payment_card"])) == D(b["card"])
        assert D(str(t["payment_cash"])) + D(str(t["payment_card"])) == D(str(t["total_amount"]))
    assert [b["receipt_ref"] for b in result["blocks"]] == result["receipt_refs"]

    mine = next(s for s in (await employee.get("/daysheets/app/mine")).json() if s["code"] == sent.json()["code"])
    assert mine["receipt_refs"] == result["receipt_refs"]
    assert mine["receipt_ref"] == result["receipt_refs"][0]
    listed = next(s for s in (await client.get("/daysheets")).json() if s["id"] == sheet_id)
    assert listed["receipt_count"] == 2

    trail = (await client.get(f"/shifts/{shift['id']}/report")).json()
    entry = next(e for e in trail["activity"] if e["action"] == "day_sheet_approved" and sent.json()["code"] in e["summary"])
    assert all(ref in entry["summary"] for ref in result["receipt_refs"])


async def test_stock_is_checked_across_all_blocks(staff, make_product, client, shift):
    employee = await staff("sheet")
    product = await make_product(stock="5")
    lines = [line(product, "3", "1.00", block=1), line(product, "3", "1.00", block=2)]
    saved = (await employee.put(f"/daysheets/app/{uuid.uuid4()}", json=body(lines, 2, card="0", counted="6"))).json()
    short = [p for p in saved["problems"] if "not enough stock" in p["message"]]
    assert short and "block 1 line 1" in short[0]["message"] and "block 2 line 1" in short[0]["message"]
    assert short[0]["block"] == 2


async def test_card_marks_never_change_the_closing_math(staff, make_product, client, shift):
    employee = await staff("sheet")
    product = await make_product(stock="10")
    lines = [line(product, "2", "10.00", pay="card"), line(product, "1", "10.00", block=2, pay="card")]
    sent = await employee.post(f"/daysheets/app/{uuid.uuid4()}/submit", json=body(lines, 2, card="12", counted="18"))
    assert sent.status_code == 200, sent.text
    totals = sent.json()["totals"]
    assert D(totals["card"]) == D("12.00") and D(totals["card_marked"]) == D("30.00")
    assert D(totals["cash_sales"]) == D("18.00") and D(totals["difference"]) == 0

    approved = (await client.post(f"/daysheets/{await waiting_id(client, sent.json()['code'])}/approve")).json()
    assert [D(b["card"]) for b in approved["blocks"]] == [D("8.00"), D("4.00")]


async def test_split_needs_a_card_part_within_the_line(staff, make_product):
    employee = await staff("sheet")
    product = await make_product(stock="10")
    token = str(uuid.uuid4())
    missing = (await employee.put(f"/daysheets/app/{token}", json=body(
        [line(product, "1", "10.00", pay="split")], 1, card="0", counted="10"))).json()
    assert any("card part" in p["message"].lower() for p in missing["problems"])
    too_big = (await employee.put(f"/daysheets/app/{token}", json=body(
        [line(product, "1", "10.00", pay="split", card="11")], 1, card="0", counted="10"))).json()
    assert any("more than the line total" in p["message"] for p in too_big["problems"])
    fine = (await employee.put(f"/daysheets/app/{token}", json=body(
        [line(product, "1", "10.00", pay="split", card="4")], 1, card="4", counted="6"))).json()
    assert fine["problems"] == []


async def test_block_limits(staff, make_product):
    employee = await staff("sheet")
    product = await make_product(stock="100000")
    put = lambda lines, blocks: employee.put(f"/daysheets/app/{uuid.uuid4()}", json=body(lines, blocks, "0", "0"))

    assert (await put([line(product, "1", "1", block=3)], 2)).status_code == 422
    assert (await put([], 21)).status_code == 422
    full = [line(product, "1", "1", block=1)] * 1000
    assert (await put(full + [line(product, "1", "1", block=1)], 2)).status_code == 422
    over_a_thousand = await put(full + [line(product, "1", "1", block=2)], 2)
    assert over_a_thousand.status_code == 200, over_a_thousand.text
    assert len(over_a_thousand.json()["content"]["lines"]) == 1001


async def test_old_phones_without_blocks_still_work(staff, make_product, client, shift):
    """A phone still on the old screen sends lines without block or pay: one block, all cash."""
    employee = await staff("sheet")
    product = await make_product(stock="5")
    old = {"lang": "pt", "content": {
        "lines": [{"product_id": product["id"], "product": product["name"], "qty": "2", "price": "3.00"}],
        "expenses": [], "card": "1", "counted": "5",
    }}
    sent = await employee.post(f"/daysheets/app/{uuid.uuid4()}/submit", json=old)
    assert sent.status_code == 200, sent.text
    assert sent.json()["content"]["blocks"] == 1
    assert sent.json()["content"]["lines"][0]["block"] == 1 and sent.json()["content"]["lines"][0]["pay"] == "cash"
    approved = (await client.post(f"/daysheets/{await waiting_id(client, sent.json()['code'])}/approve")).json()
    assert len(approved["receipt_refs"]) == 1 and D(approved["blocks"][0]["card"]) == D("1.00")
