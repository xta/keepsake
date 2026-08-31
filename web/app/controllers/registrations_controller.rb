# Signup exists only at the end of a valid invitation.
#
# Every account on this app holds live object-storage credentials, so an open
# registration form would make the operator custodian of strangers' secret
# keys. The code stays generic -- an operator who wants open signup changes
# this one controller -- but the default is closed.
class RegistrationsController < ApplicationController
  allow_unauthenticated_access
  before_action :load_invite

  rate_limit to: 10, within: 10.minutes, only: :create,
             with: -> { redirect_to root_path, alert: "Too many attempts. Try again later." }

  def new
    render inertia: "registrations/new", props: {
      token: params[:token],
      invitedEmail: @invite.email_address,
      unusableReason: @invite.unusable_reason
    }
  end

  def create
    return redirect_to(invite_path(@invite.token), alert: @invite.unusable_reason) unless @invite.usable?

    user = User.new(user_params.merge(invited_by: @invite.created_by, invited_at: Time.current))

    if user.save
      @invite.claim!(user)
      start_new_session_for user
      redirect_to libraries_path, notice: "Welcome. Add a bucket to get started."
    else
      redirect_to invite_path(@invite.token), inertia: { errors: user.errors }
    end
  end

  private
    def load_invite
      @invite = Invite.find_by(token: params[:token])
      redirect_to new_session_path, alert: "That invitation link is not valid." unless @invite
    end

    def user_params
      params.permit(:email_address, :password, :password_confirmation)
    end
end
