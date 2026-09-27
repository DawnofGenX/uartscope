"""Follow-mode (autoscroll) behaviour for the Terminal log.

Lives apart from the NiceGUI app because the logic that decides whether the
viewport should move is unavoidably JavaScript: NiceGUI elements expose no
``scrollTop``/``scrollHeight``/``clientHeight``, so Python cannot answer "is the
user parked at the newest line?" at all.

The rule, borrowed from Wireshark and every usable serial monitor:

  * follow the tail while the viewport is already at the bottom;
  * the moment the user scrolls up, hold their position and count incoming
    lines instead of yanking them back down;
  * offer a single, explicit "N new lines" control to resume.

v1 had none of this -- every re-render let the browser stick to the bottom, so
reading a burst of output mid-scroll was impossible.
"""

# Tail tolerance in CSS pixels. A strict `=== scrollHeight` test fails on
# sub-pixel rounding and silently disables following, so anything within this
# margin of the bottom counts as "at the tail".
TAIL_PX = 48


def follow_hook_js(selector: str = ".us-log", tail_px: int = TAIL_PX) -> str:
    """Return the JS that installs the follow listener on `selector`.

    The script is idempotent: re-running it (on every page build) will not stack
    a second listener onto the same element.

    It sets, on the element:
      ``__usAtTail()``  -- is the viewport at the newest line?
      ``__usFollow``   -- whether new output should scroll the viewport
      ``__usPinned``   -- has the user ever scrolled away this session?

    and calls ``window.__usOnFollowChange(boolean)`` when that flips, which is
    the single callback the Python side installs.
    """
    return """
    (() => {
      const el = document.querySelector(%(selector)s);
      if (!el || el.__usHooked) return;
      el.__usHooked = true;
      const TAIL = %(tail)d;
      const atTail = () =>
        el.scrollTop + el.clientHeight >= el.scrollHeight - TAIL;
      el.__usAtTail = atTail;
      // Start in follow mode; corrected on the first real scroll event.
      el.__usFollow = true;
      el.__usPinned = false;
      el.addEventListener('scroll', () => {
        const t = atTail();
        if (!t) el.__usPinned = true;
        else el.__usPinned = false;
        if (t !== el.__usFollow) {
          el.__usFollow = t;
          if (window.__usOnFollowChange) window.__usOnFollowChange(t);
        }
      }, {passive: true});
    })();
    """ % {"selector": repr(selector), "tail": int(tail_px)}


def scroll_to_bottom_js(selector: str = ".us-log") -> str:
    """Return the JS that parks the log viewport at the newest line."""
    return """
    (() => {
      const el = document.querySelector(%(selector)s);
      if (el) el.scrollTop = el.scrollHeight;
    })();
    """ % {"selector": repr(selector)}
