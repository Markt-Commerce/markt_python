"""A discount offered in chat has to arrive like any other message.

The server emits `discount_offered` when a seller sends one. The payload
carried the chat message, but not its `message_data` -- and `message_data`
is the only place the card in the conversation reads its terms from. So a
client listening to the event would draw an empty card, and the terms only
appeared after a refetch.

Worth a test because the failure is silent on both sides: the emit
succeeds, the message renders, and only the contents are missing.
"""

import inspect

from app.chats.services import DiscountService


class TestTheEmitCarriesWhatTheCardNeeds:
    def test_message_data_is_in_the_emitted_message(self):
        source = inspect.getsource(DiscountService.create_discount_offer)
        at = source.index("discount_offered")
        emit = source[at:]
        assert '"message_data": message_data' in emit, (
            "the discount card reads its terms from message_data; without it "
            "in the emit a live-rendered card is blank"
        )

    def test_the_event_names_the_room_it_belongs_to(self):
        # Clients match an incoming message to an open thread by room.
        source = inspect.getsource(DiscountService.create_discount_offer)
        at = source.index("discount_offered")
        emit = source[at:]
        assert '"room_id": room_id' in emit

    def test_message_data_is_built_before_it_is_emitted(self):
        # Guards the ordering: the dict has to exist by the time the emit
        # references it, or this is a NameError at runtime rather than a
        # missing field.
        source = inspect.getsource(DiscountService.create_discount_offer)
        assert source.index("message_data = {") < source.index("discount_offered")

    def test_every_field_the_card_reads_is_present(self):
        # DiscountMessageData in the app: discount_id, discount_type,
        # discount_value, expires_at, product_id, product_name,
        # minimum_order_amount, discount_message, status.
        source = inspect.getsource(DiscountService.create_discount_offer)
        start = source.index("message_data = {")
        end = source.index("chat_message = ChatMessage")
        block = source[start:end]
        for field in (
            "discount_id",
            "discount_type",
            "discount_value",
            "expires_at",
            "product_id",
            "product_name",
            "minimum_order_amount",
            "discount_message",
            "status",
        ):
            assert f'"{field}"' in block, f"card reads {field}, emit would omit it"
