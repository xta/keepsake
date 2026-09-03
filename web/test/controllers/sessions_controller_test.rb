require "test_helper"

class SessionsControllerTest < ActionDispatch::IntegrationTest
  setup { @user = User.take }

  test "new" do
    get new_session_path
    assert_response :success
  end

  test "create with valid credentials" do
    post session_path, params: { email_address: @user.email_address, password: "password" }

    assert_redirected_to root_path
    assert cookies[:session_id]
  end

  test "create with invalid credentials" do
    post session_path, params: { email_address: @user.email_address, password: "wrong" }

    assert_redirected_to new_session_path
    assert_nil cookies[:session_id]
  end

  test "an expired session is refused and cleaned up" do
    sign_in_as(@user)
    session = Current.session
    session.update_column(:last_active_at, (Session::IDLE_TIMEOUT + 1.minute).ago)

    get root_path

    assert_redirected_to new_session_path
    assert_not Session.exists?(session.id), "the dead row should not survive the request that refused it"
  end

  test "a live session slides forward" do
    sign_in_as(@user)
    session = Current.session
    session.update_column(:last_active_at, (Session::TOUCH_THROTTLE + 1.minute).ago)

    get root_path

    assert_response :success
    assert_in_delta Time.current, session.reload.last_active_at, 5.seconds
  end

  test "destroy" do
    sign_in_as(User.take)

    delete session_path

    assert_redirected_to new_session_path
    assert_empty cookies[:session_id]
  end
end
