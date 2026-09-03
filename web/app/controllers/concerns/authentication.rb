module Authentication
  extend ActiveSupport::Concern

  included do
    before_action :require_authentication
    helper_method :authenticated?
  end

  class_methods do
    def allow_unauthenticated_access(**options)
      skip_before_action :require_authentication, **options
    end
  end

  private
    def authenticated?
      resume_session
    end

    def require_authentication
      resume_session || request_authentication
    end

    def resume_session
      Current.session ||= find_session_by_cookie
    end

    def find_session_by_cookie
      return unless cookies.signed[:session_id]

      session = Session.find_by(id: cookies.signed[:session_id])
      return unless session

      # An expired session is deleted rather than merely refused. Leaving the
      # row means the same dead cookie costs a query on every request forever,
      # and leaving the cookie means the browser keeps presenting it.
      if session.expired?
        session.destroy
        cookies.delete(:session_id)
        return
      end

      session.touch_last_active
      session
    end

    def request_authentication
      # A path, not a URL. `request.url` is built from the Host header, so
      # storing one means storing wherever the request claimed to be -- and
      # handing it to `redirect_to` after login turns this into an open
      # redirect that begins, convincingly, on our own domain. A path cannot
      # leave this origin no matter what Host arrives.
      #
      # GET only: coming back to a POST by redirect means issuing a GET at a
      # route that may not answer one. `verify` is exactly that, so a session
      # dying under an open form used to end at a 404 after signing in.
      session[:return_to_after_authenticating] = request.fullpath if request.get?
      redirect_to new_session_path
    end

    def after_authentication_url
      session.delete(:return_to_after_authenticating) || root_url
    end

    def start_new_session_for(user)
      # Anything the browser was carrying before it proved who it was is not
      # ours to keep: a session id fixed by somebody else survives the login
      # otherwise. Callers that need a value from the pre-login session must
      # read it BEFORE calling this -- `after_authentication_url` is the one
      # that does, and SessionsController#create reads it first for that reason.
      reset_session

      user.sessions.create!(user_agent: request.user_agent, ip_address: request.remote_ip).tap do |session|
        Current.session = session
        # Not `permanent`, which is twenty years. The cookie is set to outlive
        # the session by exactly nothing: once the row is past its absolute
        # cap the cookie is worthless, so the browser may as well drop it.
        cookies.signed[:session_id] = {
          value: session.id,
          expires: Session::ABSOLUTE_LIFETIME.from_now,
          httponly: true,
          same_site: :lax
        }
      end
    end

    def terminate_session
      Current.session.destroy
      cookies.delete(:session_id)
    end
end
