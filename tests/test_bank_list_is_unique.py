"""The bank picker's list, which was not keyed on anything unique.

Paystack's NGN bank list is not unique on `code`: five codes come back
twice under two registered names. The rider app keyed its rows by code
and React threw "Encountered two children with the same key, .$50572" --
50572 being BANKIT MFB and BANKIT MICROFINANCE BANK LTD.

They were noise either way. `code` is the entire destination of a
transfer, so two rows carrying the same one do the same thing whichever
is picked.
"""

from app.wallet.paystack_banks import PaystackBankClient


def rows(*pairs):
    return [
        {"id": index, "name": name, "code": code, "slug": None, "type": "nuban"}
        for index, (name, code) in enumerate(pairs)
    ]


class TestOneRowPerCode:
    def test_a_duplicated_code_collapses(self):
        out = PaystackBankClient._dedupe_by_code(
            rows(("BANKIT MFB", "50572"), ("BANKIT MICROFINANCE BANK LTD", "50572"))
        )
        assert len(out) == 1

    def test_the_readable_name_wins(self):
        # These pairs are consistently a readable name and its registry
        # spelling, and the readable one is what somebody scanning a
        # list of 284 banks is looking for.
        out = PaystackBankClient._dedupe_by_code(
            rows(
                ("U&C Microfinance Bank Ltd (U AND C MFB)", "50840"),
                ("U and C MFB", "50840"),
            )
        )
        assert out[0]["name"] == "U and C MFB"

    def test_order_of_arrival_does_not_decide_it(self):
        first = PaystackBankClient._dedupe_by_code(
            rows(("Short", "1"), ("Much longer name", "1"))
        )
        second = PaystackBankClient._dedupe_by_code(
            rows(("Much longer name", "1"), ("Short", "1"))
        )
        assert first[0]["name"] == second[0]["name"] == "Short"

    def test_distinct_banks_are_all_kept(self):
        out = PaystackBankClient._dedupe_by_code(
            rows(("GTBank", "058"), ("Access Bank", "044"), ("Kuda", "090267"))
        )
        assert len(out) == 3

    def test_every_code_appears_once(self):
        out = PaystackBankClient._dedupe_by_code(
            rows(("A", "1"), ("B", "1"), ("C", "2"), ("D", "3"), ("E", "3"), ("F", "3"))
        )
        codes = [bank["code"] for bank in out]
        assert sorted(codes) == ["1", "2", "3"]

    def test_an_empty_list_is_fine(self):
        assert PaystackBankClient._dedupe_by_code([]) == []


class TestTheClientGetsSomethingUniqueToKeyOn:
    def test_id_survives_the_schema(self):
        from app.wallet.schemas import BankSchema

        out = BankSchema().dump({"id": 302, "name": "GTBank", "code": "058"})
        assert out["id"] == 302
