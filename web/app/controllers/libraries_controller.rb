class LibrariesController < ApplicationController
  before_action :load_library, only: %i[ show edit update destroy verify refresh ]

  # Where the settings page's "back" goes. An allowlist of names rather than a
  # returnable URL: the caller picks which of these, never where. A `return_to`
  # parameter would be an open redirect wearing a helpful face.
  BACK_DESTINATIONS = %w[ index library ].freeze

  PER_PAGE = 48

  def index
    libraries = Current.user.libraries.ordered.includes(:catalog)

    render inertia: "libraries/index", props: {
      libraries: libraries.map { |l| LibrarySerializer.summary(l, l.catalog) }
    }
  end

  def new
    render inertia: "libraries/form", props: {
      library: nil,
      providers: provider_options,
      backTo: { href: libraries_path, label: "All libraries" },
      from: nil
    }
  end

  def create
    library = Current.user.libraries.new(library_params)

    if library.save
      redirect_to library_path(library), notice: "Library added."
    else
      redirect_to new_library_path, inertia: { errors: library.errors }
    end
  end

  def edit
    render inertia: "libraries/form", props: {
      library: LibrarySerializer.summary(@library, @library.catalog),
      providers: provider_options,
      backTo: back_to,
      # Echoed so Refresh and Scan can carry it: without this, using either one
      # forgets you arrived from the homepage and Cancel drops you on the grid.
      from: params[:from].presence_in(BACK_DESTINATIONS)
    }
  end

  def update
    if @library.update(library_params)
      redirect_to library_path(@library), notice: "Library updated."
    else
      redirect_to edit_library_path(@library), inertia: { errors: @library.errors }
    end
  end

  def destroy
    @library.destroy!
    # Deleting a library removes stored credentials and a cached catalog. It
    # never touches the bucket -- the archive outlives this app by design.
    redirect_to libraries_path, notice: "#{@library.label} removed. Nothing in the bucket was deleted."
  end

  # The grid.
  def show
    catalog = refresh_catalog_if_needed

    items = catalog ? paged(catalog.items.newest_first) : CatalogItem.none
    client = @library.client

    render inertia: "libraries/show", props: {
      library: LibrarySerializer.summary(@library, catalog),
      items: items.map { |i| CatalogItemSerializer.call(i, client: client) },
      page: page,
      totalPages: catalog ? (catalog.item_count / PER_PAGE.to_f).ceil : 0,
      catalogMissing: @catalog_missing,
      error: @catalog_error
    }
  end

  # "Test connection". Answers the question the settings page exists to answer:
  # do these credentials reach this bucket?
  #
  # Tests the values currently in the form, but SAVES NOTHING. The button sits
  # among the fields, so testing the stored config while the form shows
  # something else would be a trap -- and a test that quietly writes is worse.
  # So: an unsaved copy, used for one request, then discarded.
  def verify
    # A separate in-memory instance of the same row: dirty with the form's
    # values, never saved. It keeps its id, so uniqueness checks exclude
    # itself rather than colliding with the record it came from.
    candidate = Library.find(@library.id)
    candidate.assign_attributes(library_params)
    candidate.validate

    if candidate.errors.any?
      return redirect_to edit_library_path(@library), alert: candidate.errors.full_messages.to_sentence
    end

    Keepsake::Client.for(candidate).head_bucket
    state = begin
      Keepsake::Client.for(candidate).get_index
      "index.json found"
    rescue Keepsake::CatalogMissing
      "connected, but this bucket has no index.json yet"
    end

    redirect_to edit_library_path(@library), notice: "Connection works. #{state}."
  rescue Keepsake::StorageError => e
    redirect_to edit_library_path(@library), alert: e.message
  end

  def refresh
    Keepsake::CatalogSync.new(@library).call(force: true)
    redirect_to edit_library_path(@library, from: params[:from]), notice: "Catalog refreshed."
  rescue Keepsake::CatalogMissing => e
    redirect_to edit_library_path(@library, from: params[:from]), alert: e.message
  rescue Keepsake::StorageError => e
    redirect_to edit_library_path(@library, from: params[:from]), alert: e.message
  end

  private
    def load_library
      @library = Current.user.libraries.find_by(id: params[:id])
      # 404 rather than 403: whether a library exists is not this user's
      # business either way.
      raise ActionController::RoutingError, "Not Found" unless @library&.viewable_by?(Current.user)
    end

    def library_params
      permitted = params.permit(
        :label, :provider, :endpoint, :region, :bucket, :prefix,
        :force_path_style, :access_level, :access_key_id, :secret_access_key, :account_id
      )
      # A blank secret on update means "leave the stored one alone", which is
      # what lets the form show a hint instead of the credential.
      permitted.delete(:secret_access_key) if @library && permitted[:secret_access_key].blank?
      permitted
    end

    def provider_options
      Keepsake::Provider.form_metadata.slice(*Keepsake::Provider.selectable)
    end

    # Resolves the allowlisted name to a path here, so no caller-supplied string
    # ever reaches redirect_to or a href.
    def back_to
      case params[:from].presence_in(BACK_DESTINATIONS)
      when "index" then { href: libraries_path, label: "All libraries" }
      else { href: library_path(@library), label: @library.label }
      end
    end

    def page = [ params[:page].to_i, 1 ].max

    def paged(scope) = scope.limit(PER_PAGE).offset((page - 1) * PER_PAGE)

    # A viewer should not have to press Refresh to see anything at all. Fetch
    # on first view and when the cache has aged out; surface failures rather
    # than rendering an empty grid that looks like an empty bucket.
    def refresh_catalog_if_needed
      Keepsake::CatalogSync.new(@library).call
    rescue Keepsake::CatalogMissing
      @catalog_missing = true
      @library.catalog
    rescue Keepsake::StorageError => e
      @catalog_error = e.message
      @library.catalog
    end
end
