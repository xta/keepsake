Rails.application.routes.draw do
  resource :session, only: %i[ new create destroy ]
  resources :passwords, param: :token, only: %i[ new create edit update ]

  # Signup exists only behind an invitation. See RegistrationsController.
  get  "invites/:token", to: "registrations#new",    as: :invite
  post "invites/:token", to: "registrations#create"

  resources :libraries do
    member do
      post :verify   # "Test connection"
      post :refresh  # refetch index.json
    end
    resources :items, only: %i[ show update ] do
      member { post :enrich }
    end

    # Adopting media uploaded by another route. Only ever reachable on a
    # library whose key can write.
    resource :sweep, only: %i[ show create ], module: :libraries
  end

  # The local-directory backend's byte server. Never drawn outside development
  # and test, so it cannot be reached in a real deployment even by accident.
  if Rails.env.local?
    get "dev/media/:library_id", to: "dev/media#show", as: :dev_media
  end

  # Reveal health status on /up that returns 200 if the app boots with no exceptions, otherwise 500.
  get "up" => "rails/health#show", as: :rails_health_check

  root "libraries#index"

  # Redirect to localhost from 127.0.0.1 to use same IP address with Vite server.
  #
  # Development and test only. The Vite dev server is the only reason the two
  # hostnames have to agree, so a catch-all matching every path has no business
  # being drawn in a real deployment. Stays last, where it cannot shadow a route
  # above it.
  if Rails.env.local?
    constraints(host: "127.0.0.1") do
      get "(*path)", to: redirect { |params, req| "#{req.protocol}localhost:#{req.port}/#{params[:path]}" }
    end
  end
end
