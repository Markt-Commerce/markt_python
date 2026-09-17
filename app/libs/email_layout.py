"""Email-safe building blocks.

Email is not the web. Gmail strips most of a `<style>` block, Outlook renders
through Word, and neither supports flexbox or CSS grid -- so the existing
templates, which lay their stats out with `display: grid`, collapse into a
stack of divs in exactly the clients everyone uses. Layout here is tables and
inline styles, which is ugly to write and the only thing that renders the same
everywhere.

Everything is a plain string helper rather than a template engine, because
that is what the rest of email_service.py already does and one convention
beats two.
"""

from typing import List, Optional

BRAND = "#E94C2A"
INK = "#1A1A1A"
MUTED = "#6B7280"
HAIRLINE = "#E5E7EB"
PAGE = "#F5F5F4"
CARD = "#FFFFFF"

# 600px is the width every client agrees on; wider gets cut off in Outlook's
# reading pane and on a phone.
WIDTH = 600


def shell(title: str, preheader: str, body: str, footer_note: str = "") -> str:
    """Wrap content in the outer table every client can render.

    `preheader` is the grey line shown after the subject in an inbox list. It
    is hidden in the body itself -- without one, clients show whatever text
    comes first, which is usually "View in browser" or the logo's alt text.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light">
<title>{title}</title>
</head>
<body style="margin:0;padding:0;background:{PAGE};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:{PAGE};padding:24px 12px;">
  <tr><td align="center">
    <table role="presentation" width="{WIDTH}" cellpadding="0" cellspacing="0"
           style="width:100%;max-width:{WIDTH}px;background:{CARD};
                  border-radius:14px;overflow:hidden;
                  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
                  Roboto,Helvetica,Arial,sans-serif;">
      {body}
    </table>
    <table role="presentation" width="{WIDTH}" cellpadding="0" cellspacing="0"
           style="width:100%;max-width:{WIDTH}px;">
      <tr><td style="padding:16px 24px;text-align:center;color:{MUTED};
                     font-size:12px;line-height:18px;
                     font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
                     Roboto,Helvetica,Arial,sans-serif;">
        {footer_note or "You're receiving this because you sell on Markt."}
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""


def header(eyebrow: str, headline: str) -> str:
    """The brand band and the one sentence that says what this is."""
    return f"""
      <tr><td style="background:{BRAND};padding:28px 24px;">
        <div style="color:#FFFFFF;opacity:.85;font-size:12px;font-weight:600;
                    letter-spacing:.08em;text-transform:uppercase;">{eyebrow}</div>
        <div style="color:#FFFFFF;font-size:26px;font-weight:700;
                    line-height:32px;margin-top:6px;">{headline}</div>
      </td></tr>"""


def lead_stat(value: str, label: str, context: str = "") -> str:
    """The one number the email is about, big enough to read at a glance."""
    context_html = (
        f'<div style="color:{MUTED};font-size:14px;margin-top:6px;">{context}</div>'
        if context
        else ""
    )
    return f"""
      <tr><td style="padding:28px 24px 8px;">
        <div style="color:{MUTED};font-size:13px;font-weight:600;">{label}</div>
        <div style="color:{INK};font-size:40px;font-weight:700;
                    line-height:46px;margin-top:4px;">{value}</div>
        {context_html}
      </td></tr>"""


def stat_row(label: str, value: str, context: str = "") -> str:
    """One supporting figure.

    A row, not a grid cell: the two-column grid the old template used renders
    as a stack in Gmail anyway, and a row reads better on a phone.
    """
    context_html = (
        f'<div style="color:{MUTED};font-size:13px;margin-top:2px;">{context}</div>'
        if context
        else ""
    )
    return f"""
      <tr><td style="padding:0 24px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="border-top:1px solid {HAIRLINE};">
          <tr>
            <td style="padding:16px 0;">
              <div style="color:{INK};font-size:15px;font-weight:600;">{label}</div>
              {context_html}
            </td>
            <td align="right" style="padding:16px 0;color:{INK};
                                     font-size:22px;font-weight:700;
                                     white-space:nowrap;">{value}</td>
          </tr>
        </table>
      </td></tr>"""


def button(text: str, url: str) -> str:
    """A table-based button, which survives Outlook. A padded <a> does not."""
    return f"""
      <tr><td style="padding:8px 24px 28px;">
        <table role="presentation" cellpadding="0" cellspacing="0">
          <tr><td style="background:{BRAND};border-radius:10px;">
            <a href="{url}" style="display:inline-block;padding:13px 26px;
               color:#FFFFFF;font-size:15px;font-weight:700;
               text-decoration:none;">{text}</a>
          </td></tr>
        </table>
      </td></tr>"""


def table_block(headings: List[str], rows: List[List[str]], title: str = "") -> str:
    """A simple data table. Returns "" for no rows, so a section with nothing
    in it disappears rather than printing an empty frame."""
    if not rows:
        return ""

    title_html = (
        f'<div style="color:{INK};font-size:16px;font-weight:700;'
        f'margin-bottom:10px;">{title}</div>'
        if title
        else ""
    )
    head = "".join(
        f'<th align="{"right" if i else "left"}" style="padding:8px 0;'
        f"color:{MUTED};font-size:12px;font-weight:600;text-transform:uppercase;"
        f'letter-spacing:.05em;border-bottom:1px solid {HAIRLINE};">{h}</th>'
        for i, h in enumerate(headings)
    )
    body = ""
    for row in rows:
        cells = "".join(
            f'<td align="{"right" if i else "left"}" style="padding:12px 0;'
            f"color:{INK};font-size:14px;"
            f'border-bottom:1px solid {HAIRLINE};">{c}</td>'
            for i, c in enumerate(row)
        )
        body += f"<tr>{cells}</tr>"

    return f"""
      <tr><td style="padding:20px 24px 4px;">
        {title_html}
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
          <tr>{head}</tr>
          {body}
        </table>
      </td></tr>"""


def note(text: str) -> str:
    return f"""
      <tr><td style="padding:16px 24px 24px;color:{MUTED};font-size:13px;
                     line-height:20px;">{text}</td></tr>"""


def change_line(
    current: float, previous: Optional[float], noun: str, prefix: str = ""
) -> str:
    """ "12 more than last month", or nothing.

    A number on its own is not information -- the reader has nothing to
    compare it against. But an invented comparison is worse than none, so this
    returns "" when the previous period was not supplied.
    """
    if previous is None:
        return ""
    delta = current - previous
    if delta == 0:
        return f"Same as the {noun} before."
    if delta > 0:
        return f"{prefix}{_fmt(delta)} more than the {noun} before."
    return f"{prefix}{_fmt(abs(delta))} less than the {noun} before."


def _fmt(value: float) -> str:
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.2f}"
