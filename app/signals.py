"""Application-wide domain signals (blinker; already a Flask dependency).

These decouple feature modules: an emitter (e.g. orders) fires a signal after
its own commit, and any number of listeners (e.g. gamification) react. The
emitter knows nothing about the listeners, so a feature can be turned off by
simply not importing its events module.

Emit *after* your own DB commit — listeners open their own transactions.
"""

from blinker import Namespace

_signals = Namespace()

# Orders
order_completed = _signals.signal("order-completed")  # kw: order
order_reversed = _signals.signal("order-reversed")  # kw: order

# Social
post_created = _signals.signal("post-created")  # kw: post
post_reaction_added = _signals.signal("post-reaction-added")  # kw: post, reactor_id

# Reviews
review_created = _signals.signal("review-created")  # kw: review

# Users
profile_completed = _signals.signal("profile-completed")  # kw: user_id
referral_first_paid = _signals.signal(
    "referral-first-paid"
)  # kw: referrer_id, referee_id
daily_login = _signals.signal("daily-login")  # kw: user_id
seller_verified = _signals.signal("seller-verified")  # kw: user_id
