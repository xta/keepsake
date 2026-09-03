require "active_support/core_ext/integer/time"

Rails.application.configure do
  # Settings specified here will take precedence over those in config/application.rb.

  # Code is not reloaded between requests.
  config.enable_reloading = false

  # Eager load code on boot for better performance and memory savings (ignored by Rake tasks).
  config.eager_load = true

  # Full error reports are disabled.
  config.consider_all_requests_local = false

  # Turn on fragment caching in view templates.
  config.action_controller.perform_caching = true

  # Cache assets for far-future expiry since they are all digest stamped.
  config.public_file_server.headers = { "cache-control" => "public, max-age=#{1.year.to_i}" }

  # Enable serving of images, stylesheets, and JavaScripts from an asset server.
  # config.asset_host = "http://assets.example.com"

  # Assume all access to the app is happening through a SSL-terminating reverse proxy.
  # kamal-proxy terminates TLS and forwards over plain HTTP on the private
  # Docker network, so Rails must be told the original request was secure --
  # otherwise force_ssl below would redirect forever.
  config.assume_ssl = true

  # Force all access to the app over SSL, use Strict-Transport-Security, and use secure cookies.
  config.force_ssl = true

  # Skip http-to-https redirect for the default health check endpoint.
  # The health check is requested over plain HTTP from inside the network; a
  # redirect there would make the container look permanently unhealthy.
  config.ssl_options = { redirect: { exclude: ->(request) { request.path == "/up" } } }

  # Log to STDOUT with the current request id as a default log tag.
  config.log_tags = [ :request_id ]
  config.logger   = ActiveSupport::TaggedLogging.logger(STDOUT)

  # Change to "debug" to log everything (including potentially personally-identifiable information!).
  config.log_level = ENV.fetch("RAILS_LOG_LEVEL", "info")

  # Prevent health checks from clogging up the logs.
  config.silence_healthcheck_path = "/up"

  # Don't log any deprecations.
  config.active_support.report_deprecations = false

  # Replace the default in-process memory cache store with a durable alternative.
  config.cache_store = :solid_cache_store

  # Replace the default in-process and non-durable queuing backend for Active Job.
  config.active_job.queue_adapter = :solid_queue
  config.solid_queue.connects_to = { database: { writing: :queue } }

  # Unmount Action Cable. Its engine mounts /cable whether or not anything uses
  # it, and nothing here does: this app declares no channels, and the sweep page
  # reports progress by polling. What was left was an endpoint whose only
  # possible answer was to reject the connection.
  config.action_cable.mount_path = nil

  # Ignore bad email addresses and do not raise email delivery errors.
  # Set this to true and configure the email server for immediate delivery to raise delivery errors.
  # config.action_mailer.raise_delivery_errors = false

  # Set host to be used by links generated in mailer templates.
  # Absolute URLs need the app's own host: a mailer has no request to infer it
  # from. The generated default here was literally "example.com", which sends
  # every password reset link into the void.
  config.action_mailer.default_url_options = { host: ENV.fetch("APP_HOST", "localhost"), protocol: "https" }
  config.action_controller.default_url_options = { host: ENV.fetch("APP_HOST", "localhost"), protocol: "https" }

  # Specify outgoing SMTP server. Remember to add smtp/* credentials via bin/rails credentials:edit.
  # config.action_mailer.smtp_settings = {
  #   user_name: Rails.application.credentials.dig(:smtp, :user_name),
  #   password: Rails.application.credentials.dig(:smtp, :password),
  #   address: "smtp.example.com",
  #   port: 587,
  #   authentication: :plain
  # }

  # Enable locale fallbacks for I18n (makes lookups for any locale fall back to
  # the I18n.default_locale when a translation cannot be found).
  config.i18n.fallbacks = true

  # Do not dump schema after migrations.
  config.active_record.dump_schema_after_migration = false

  # Only use :id for inspections in production.
  config.active_record.attributes_for_inspect = [ :id ]

  # Enable DNS rebinding protection and other `Host` header attacks.
  #
  # Rails builds absolute URLs from the incoming Host header, so an unchecked
  # Host is an attacker deciding what this site's own URLs are. kamal-proxy
  # already routes by Host and 404s anything it does not recognise, which means
  # nothing reaches here with a forged one today -- but that protection lives
  # entirely at the edge, and this app should not depend on what is in front of
  # it. An empty list allows everything, so a missing APP_HOST is no worse than
  # the previous behaviour rather than a silent lockout.
  config.hosts = [ ENV.fetch("APP_HOST", nil) ].compact

  # Skip DNS rebinding protection for the default health check endpoint.
  # Kamal healthchecks the container by address, so that request's Host is the
  # container's, never APP_HOST. Without this exclusion every deploy would wait
  # on a container that can never report healthy.
  config.host_authorization = { exclude: ->(request) { request.path == "/up" } }
end
