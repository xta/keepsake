# One signed-in browser.
#
# A session row is the whole of a login: the cookie carries nothing but this
# record's id, so deleting the row ends the session everywhere, immediately.
#
# Sessions expire two ways. Idle expiry ends one that has gone quiet, which is
# the case that matters -- a cookie copied off a machine nobody uses any more
# is worth nothing a fortnight later. The absolute cap ends one that has been
# used the whole time, because a session that never expires is a password that
# was only ever typed once.
class Session < ApplicationRecord
  IDLE_TIMEOUT = 14.days
  ABSOLUTE_LIFETIME = 90.days

  # Writing on every request would turn each page view into a database write to
  # move a number that is measured in days. Hour granularity is far finer than
  # the timeout needs.
  TOUCH_THROTTLE = 1.hour

  belongs_to :user

  scope :expired, -> {
    where(last_active_at: ...IDLE_TIMEOUT.ago).or(where(created_at: ...ABSOLUTE_LIFETIME.ago))
  }

  before_create { self.last_active_at ||= Time.current }

  def expired?
    last_active_at < IDLE_TIMEOUT.ago || created_at < ABSOLUTE_LIFETIME.ago
  end

  # Deliberately update_column: no callbacks, no updated_at, no validations.
  # This runs on requests that are otherwise pure reads.
  def touch_last_active
    return if last_active_at.after?(TOUCH_THROTTLE.ago)
    update_column(:last_active_at, Time.current)
  end
end
