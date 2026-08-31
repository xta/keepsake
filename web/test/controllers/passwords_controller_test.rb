require "test_helper"

class PasswordsControllerTest < ActionDispatch::IntegrationTest
  setup { @user = User.take }

  test "new" do
    get new_password_path
    assert_response :success
  end

  test "create" do
    post passwords_path, params: { email_address: @user.email_address }
    assert_enqueued_email_with PasswordsMailer, :reset, args: [ @user ]
    assert_redirected_to new_session_path

    follow_redirect!
    assert_notice "reset link is on its way"
  end

  test "create for an unknown user redirects but sends no mail" do
    post passwords_path, params: { email_address: "missing-user@example.com" }
    assert_enqueued_emails 0
    assert_redirected_to new_session_path

    follow_redirect!
    assert_notice "reset link is on its way"
  end

  test "edit" do
    get edit_password_path(@user.password_reset_token)
    assert_response :success
  end

  test "edit with invalid password reset token" do
    get edit_password_path("invalid token")
    assert_redirected_to new_password_path

    follow_redirect!
    # An invalid link is an alert, not a notice. The generated version of this
    # test used assert_select "div", which matched either kind and so never
    # checked which one it got.
    assert_flash :alert, /reset link is invalid/
  end

  test "update" do
    assert_changes -> { @user.reload.password_digest } do
      put password_path(@user.password_reset_token), params: { password: "new-password", password_confirmation: "new-password" }
      assert_redirected_to new_session_path
    end

    follow_redirect!
    assert_notice "Password has been reset"
  end

  test "update with non matching passwords" do
    token = @user.password_reset_token
    assert_no_changes -> { @user.reload.password_digest } do
      put password_path(token), params: { password: "long-enough", password_confirmation: "does-not-match" }
      assert_redirected_to edit_password_path(token)
    end

    follow_redirect!
    assert_flash :alert, /doesn.t match/i
  end

  private
    # The flash reaches the page as an Inertia prop, not as markup: the wording
    # lives in the Vue component and is never server-rendered.
    def assert_notice(text)
      assert_flash :notice, /#{text}/
    end
end
