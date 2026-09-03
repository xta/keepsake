require "test_helper"

class SessionTest < ActiveSupport::TestCase
  setup { @user = User.take }

  test "a new session starts active" do
    session = @user.sessions.create!
    assert_not session.expired?
  end

  test "expires after going idle" do
    session = @user.sessions.create!
    session.update_column(:last_active_at, (Session::IDLE_TIMEOUT + 1.minute).ago)

    assert session.expired?
  end

  test "expires at the absolute cap even while in use" do
    session = @user.sessions.create!
    session.update_columns(
      created_at: (Session::ABSOLUTE_LIFETIME + 1.minute).ago,
      last_active_at: Time.current
    )

    assert session.expired?
  end

  test "touch_last_active is throttled" do
    session = @user.sessions.create!
    original = session.last_active_at

    session.touch_last_active
    assert_equal original.to_i, session.reload.last_active_at.to_i

    session.update_column(:last_active_at, (Session::TOUCH_THROTTLE + 1.minute).ago)
    session.touch_last_active
    assert_in_delta Time.current, session.reload.last_active_at, 5.seconds
  end

  test "expired scope finds both kinds and spares the living" do
    idle = @user.sessions.create!
    idle.update_column(:last_active_at, (Session::IDLE_TIMEOUT + 1.minute).ago)

    old = @user.sessions.create!
    old.update_column(:created_at, (Session::ABSOLUTE_LIFETIME + 1.minute).ago)

    alive = @user.sessions.create!

    expired = Session.expired.to_a
    assert_includes expired, idle
    assert_includes expired, old
    assert_not_includes expired, alive
  end
end
