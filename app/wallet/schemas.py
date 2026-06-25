from marshmallow import Schema, fields, validate


class WalletBalanceSchema(Schema):
    currency = fields.Str()
    available_balance = fields.Float()


class WalletTransactionSchema(Schema):
    id = fields.Int()
    type = fields.Str()
    amount = fields.Float()
    balance_after = fields.Float()
    reference_type = fields.Str()
    reference_id = fields.Str()
    description = fields.Str()
    created_at = fields.Str()


class WalletTransactionsResponseSchema(Schema):
    transactions = fields.Nested(WalletTransactionSchema, many=True)
    pagination = fields.Dict()


class WithdrawalRequestSchema(Schema):
    amount = fields.Float(required=True, validate=validate.Range(min=1))
    currency = fields.Str(missing="NGN")
    bank_code = fields.Str(required=True)
    account_number = fields.Str(required=True)
    account_name = fields.Str(required=True)


class WithdrawalListResponseSchema(Schema):
    withdrawals = fields.List(fields.Dict())
    pagination = fields.Dict()


class WithdrawalResponseSchema(Schema):
    id = fields.Str()
    amount = fields.Float()
    currency = fields.Str()
    status = fields.Str()
    created_at = fields.DateTime()


class TopUpInitializeSchema(Schema):
    amount = fields.Float(required=True, validate=validate.Range(min=100))
    currency = fields.Str(missing="NGN")
    platform = fields.Str(missing="web")


class TopUpInitializeResponseSchema(Schema):
    topup_id = fields.Str()
    amount = fields.Float()
    currency = fields.Str()
    authorization_url = fields.Str()
    reference = fields.Str()


class SellerPayoutAccountSchema(Schema):
    bank_code = fields.Str(required=True)
    account_number = fields.Str(required=True)
    account_name = fields.Str(required=True)


class SellerPayoutAccountResponseSchema(Schema):
    seller_id = fields.Int()
    subaccount_code = fields.Str()
    account_name = fields.Str()
    account_number_masked = fields.Str()
