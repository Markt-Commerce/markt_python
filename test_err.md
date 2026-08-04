=================================== FAILURES ===================================
_____________________ test_complete_payment_is_idempotent ______________________
/opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/unittest/mock.py:900: in assert_not_called
    raise AssertionError(msg)
E   AssertionError: Expected '_send_payment_notifications' to not have been called. Called 1 times.
E   Calls: [call(<MagicMock name='session_scope().__enter__().query().with_for_update().filter_by().first()' id='140093332472080'>, <PaymentStatus.COMPLETED: 'completed'>)].

During handling of the above exception, another exception occurred:
tests/test_payment_complete.py:66: in test_complete_payment_is_idempotent
    mock_notify.assert_not_called()
E   AssertionError: Expected '_send_payment_notifications' to not have been called. Called 1 times.
E   Calls: [call(<MagicMock name='session_scope().__enter__().query().with_for_update().filter_by().first()' id='140093332472080'>, <PaymentStatus.COMPLETED: 'completed'>)].
E   
E   pytest introspection follows:
E   
E   Args:
E   assert (<MagicMock n... 'completed'>) == ()
E     
E     Left contains 2 more items, first extra item: <MagicMock name='session_scope().__enter__().query().with_for_update().filter_by().first()' id='140093332472080'>
E     
E     Full diff:
E     - ()
E     + (
E     +     <MagicMock name='session_scope().__enter__().query().with_for_update().filter_by().first()' id='140093332472080'>,
E     +     <PaymentStatus.COMPLETED: 'completed'>,
E     + )
=============================== warnings summary ===============================
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:949: 11 warnings
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:949: RemovedInMarshmallow4Warning: The 'default' argument to fields is deprecated. Use 'dump_default' instead.
    super().__init__(**kwargs)

app/libs/schemas.py:22
  /home/runner/work/markt_python/markt_python/app/libs/schemas.py:22: RemovedInMarshmallow4Warning: The 'default' argument to fields is deprecated. Use 'dump_default' instead.
    operator = fields.Str(required=False, default="eq")

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181: RemovedInMarshmallow4Warning: The 'default' argument to fields is deprecated. Use 'dump_default' instead.
    super().__init__(**kwargs)

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755: RemovedInMarshmallow4Warning: The 'default' argument to fields is deprecated. Use 'dump_default' instead.
    super().__init__(**kwargs)

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755: RemovedInMarshmallow4Warning: Passing field metadata as keyword arguments is deprecated. Use the explicit `metadata=...` argument instead. Additional metadata: {'description': 'List of category IDs'}
    super().__init__(**kwargs)

app/users/schemas.py:116
  /home/runner/work/markt_python/markt_python/app/users/schemas.py:116: RemovedInMarshmallow4Warning: Passing field metadata as keyword arguments is deprecated. Use the explicit `metadata=...` argument instead. Additional metadata: {'description': 'Optional: If not provided, will use current_role or default to available account type'}
    account_type = fields.Str(

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:949: 10 warnings
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:949: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    super().__init__(**kwargs)

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755: RemovedInMarshmallow4Warning: Passing field metadata as keyword arguments is deprecated. Use the explicit `metadata=...` argument instead. Additional metadata: {'description': 'List of media IDs to link to product'}
    super().__init__(**kwargs)

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1890
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1890: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    super().__init__(**kwargs)

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1181: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    super().__init__(**kwargs)

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    super().__init__(**kwargs)

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1571
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1571
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1571
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:1571: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    super().__init__(**kwargs)

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755: RemovedInMarshmallow4Warning: Passing field metadata as keyword arguments is deprecated. Use the explicit `metadata=...` argument instead. Additional metadata: {'description': 'List of media IDs to link to post'}
    super().__init__(**kwargs)

app/socials/schemas.py:146
  /home/runner/work/markt_python/markt_python/app/socials/schemas.py:146: RemovedInMarshmallow4Warning: The 'default' argument to fields is deprecated. Use 'dump_default' instead.
    status = fields.Str(

app/socials/schemas.py:255
  /home/runner/work/markt_python/markt_python/app/socials/schemas.py:255: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    target_type = fields.Str(

app/socials/schemas.py:330
  /home/runner/work/markt_python/markt_python/app/socials/schemas.py:330: RemovedInMarshmallow4Warning: The 'default' argument to fields is deprecated. Use 'dump_default' instead.
    status = fields.Str(

app/payments/schemas.py:38
  /home/runner/work/markt_python/markt_python/app/payments/schemas.py:38: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    currency = fields.Str(validate=validate.Length(equal=3), missing="NGN")

app/payments/schemas.py:39
  /home/runner/work/markt_python/markt_python/app/payments/schemas.py:39: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    method = fields.Str(missing="card")  # PaymentMethod.CARD.value

app/payments/schemas.py:102
  /home/runner/work/markt_python/markt_python/app/payments/schemas.py:102: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    currency = fields.Str(missing="NGN")

app/chats/schemas.py:30
  /home/runner/work/markt_python/markt_python/app/chats/schemas.py:30: RemovedInMarshmallow4Warning: The 'default' argument to fields is deprecated. Use 'dump_default' instead.
    message_type = fields.String(

app/chats/schemas.py:64
  /home/runner/work/markt_python/markt_python/app/chats/schemas.py:64: RemovedInMarshmallow4Warning: The 'default' argument to fields is deprecated. Use 'dump_default' instead.
    message_type = fields.String(

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/marshmallow/fields.py:755: RemovedInMarshmallow4Warning: Passing field metadata as keyword arguments is deprecated. Use the explicit `metadata=...` argument instead. Additional metadata: {'description': 'List of media IDs to link to request'}
    super().__init__(**kwargs)

app/wallet/schemas.py:27
  /home/runner/work/markt_python/markt_python/app/wallet/schemas.py:27: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    currency = fields.Str(missing="NGN")

app/wallet/schemas.py:48
  /home/runner/work/markt_python/markt_python/app/wallet/schemas.py:48: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    currency = fields.Str(missing="NGN")

app/wallet/schemas.py:49
  /home/runner/work/markt_python/markt_python/app/wallet/schemas.py:49: RemovedInMarshmallow4Warning: The 'missing' argument to fields is deprecated. Use 'load_default' instead.
    platform = fields.Str(missing="web")

../../../../../opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/apispec/ext/marshmallow/openapi.py:134
tests/test_api_smoke.py::TestDeprecatedOrderCreateEndpoint::test_post_orders_returns_410
tests/test_api_smoke.py::TestCheckoutAuthSmoke::test_checkout_requires_auth
tests/test_api_smoke.py::TestWalletAuthSmoke::test_wallet_requires_auth
tests/test_api_smoke.py::TestOrderCancelAuthSmoke::test_cancel_requires_auth
tests/test_api_smoke.py::TestOrderTrackAuthSmoke::test_track_requires_auth
tests/test_api_smoke.py::TestWalletWithdrawalsAuthSmoke::test_withdrawals_requires_auth
  /opt/hostedtoolcache/Python/3.11.15/x64/lib/python3.11/site-packages/apispec/ext/marshmallow/openapi.py:134: UserWarning: Multiple schemas resolved to the name PublicProfile. The name has been modified. Either manually add each of the schemas with a different name or provide a custom schema_name_resolver.
    name = get_unique_schema_name(self.spec.components, name)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_payment_complete.py::test_complete_payment_is_idempotent - AssertionError: Expected '_send_payment_notifications' to not have been called. Called 1 times.
Calls: [call(<MagicMock name='session_scope().__enter__().query().with_for_update().filter_by().first()' id='140093332472080'>, <PaymentStatus.COMPLETED: 'completed'>)].

pytest introspection follows:./.;

Args:
assert (<MagicMock n... 'completed'>) == ()
  
  Left contains 2 more items, first extra item: <MagicMock name='session_scope().__enter__().query().with_for_update().filter_by().first()' id='140093332472080'>
  
  Full diff:
  - ()
  + (
  +     <MagicMock name='session_scope().__enter__().query().with_for_update().filter_by().first()' id='140093332472080'>,
  +     <PaymentStatus.COMPLETED: 'completed'>,
  + )
================== 1 failed, 89 passed, 70 warnings in 2.57s ===================