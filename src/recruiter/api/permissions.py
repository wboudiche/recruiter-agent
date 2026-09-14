"""Who may do what — the viewer read-only policy, in one place.

Default-deny by design: a viewer is refused every mutating method unless
the route template appears below. A route added later is therefore closed
to viewers until someone opts it in deliberately, rather than silently
shipping open. That trade is the point — the surprise moves from
"shipped open" to "shipped closed", which is the direction worth having.

The interviewer-sheet routes are the second deliberate exception (chat was
the first): a viewer can be an interviewer, and an interviewer must write
their own feedback. See docs/superpowers/specs/2026-09-14-multi-interviewer-design.md.
"""

MUTATING_METHODS = frozenset({"POST", "PATCH", "PUT", "DELETE"})

# (method, route TEMPLATE) — templates, not concrete paths, so ids in
# URLs never have to be matched with a regex.
VIEWER_ALLOWED_ROUTES = frozenset({
    # Chat is the reason a viewer account is worth having: a hiring
    # manager can interrogate a shortlist. Safe here only because the
    # agent withholds its write tools from viewers (see agent/tools.py);
    # allowlisting this route WITHOUT that filter would let a viewer
    # validate and reject candidates by conversation.
    ("POST", "/api/applications/{application_id}/chat"),
    # Every role changes its own password.
    ("POST", "/api/auth/password"),
    # Refusing logout would be absurd.
    ("POST", "/api/auth/logout"),
    # Anonymous anyway — the guard never sees a user here. Listed so a
    # future refactor that authenticates earlier cannot break login.
    ("POST", "/api/auth/login/password"),
    # Interviewer sheets. A viewer assigned to a candidate may write exactly
    # one thing: their own sheet on that candidate. The allow list is per
    # route, so it cannot express "own sheet only" — each handler in
    # api/interview.py checks the assignment row itself (404 when
    # unassigned, 409 when submitted). Allow-listing these WITHOUT that row
    # check would let any viewer write feedback on any candidate. The kit
    # PATCH is here because an interviewer may APPEND a question; the
    # handler refuses every other change from a non-recruiter with 403.
    ("PATCH", "/api/applications/{application_id}/interview-kit/sheet"),
    ("POST", "/api/applications/{application_id}/interview-kit/sheet/submit"),
    ("PATCH", "/api/applications/{application_id}/interview-kit"),
})
