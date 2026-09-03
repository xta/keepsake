class SessionsController < ApplicationController
  allow_unauthenticated_access only: %i[ new create ]
  rate_limit to: 10, within: 3.minutes, only: :create,
             with: -> { redirect_to new_session_path, alert: "Too many attempts. Try again in a few minutes." }

  def new
    render inertia: "sessions/new"
  end

  def create
    # Defaulted, not just permitted. `authenticate_by` raises ArgumentError when
    # either key is ABSENT -- blank is fine, missing is not -- so a POST with no
    # body was a 500 that anyone could trigger without an account. Empty strings
    # take the ordinary "no such user" path, dummy digest and all.
    credentials = params.permit(:email_address, :password)
      .with_defaults(email_address: "", password: "")

    if user = User.authenticate_by(credentials)
      # Read first: start_new_session_for resets the session, which is where
      # this was stored. Reversed, every sign-in lands on the root page and the
      # "carry on where you were going" behaviour disappears without a sound.
      target = after_authentication_url
      start_new_session_for user
      redirect_to target
    else
      # Deliberately does not say which half was wrong: that difference tells
      # an attacker whether an address has an account here.
      redirect_to new_session_path, alert: "Try another email address or password."
    end
  end

  def destroy
    terminate_session
    redirect_to new_session_path, status: :see_other
  end
end
