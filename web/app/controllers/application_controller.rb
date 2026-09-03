class ApplicationController < ActionController::Base
  include Authentication

  # Only allow modern browsers supporting webp images, web push, badges, import maps, CSS nesting, and CSS :has.
  allow_browser versions: :modern

  inertia_share do
    {
      currentUser: current_user_props,
      flash: { notice: flash.notice, alert: flash.alert }.compact
    }
  end

  private
    def current_user_props
      return nil unless Current.user
      {
        id: Current.user.id,
        emailAddress: Current.user.email_address,
        organizationName: Current.organization&.name
      }
    end
end
