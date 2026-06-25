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


class WithdrawalResponseSchema(Schema):
    id = fields.Str()
    amount = fields.Float()
    currency = fields.Str()
    status = fields.Str()
    created_at = fields.DateTime()
