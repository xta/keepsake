module Libraries
  # Adopting media that arrived by another route -- a phone upload app, say --
  # by writing the sidecars keepsake needs and rebuilding index.json.
  #
  # Two steps on purpose. `show` reads the bucket and reports what it would do;
  # `create` does it. Nothing is written that was not shown first.
  class SweepsController < ApplicationController
    before_action :load_library
    # Both steps are gated: `show` too, so a read-only library cannot even see
    # the page, rather than being shown a plan it will be refused.
    before_action :ensure_writable

    def show
      plan = Keepsake::Sweep.new(@library).plan

      render inertia: "libraries/sweep", props: {
        library: LibrarySerializer.call(@library),
        adoptable: plan[:adoptable],
        alreadyIndexed: plan[:already_indexed],
        problems: plan[:problems]
      }
    rescue Keepsake::StorageError => e
      redirect_to library_path(@library), alert: e.message
    end

    def create
      result = Keepsake::Sweep.new(@library).apply

      # The cached catalog is now behind the bucket it mirrors.
      Keepsake::CatalogSync.new(@library).call(force: true)

      notice =
        if result[:adopted].empty?
          "Nothing new to adopt. Catalog rebuilt with #{result[:count]} #{'item'.pluralize(result[:count])}."
        else
          "Adopted #{result[:adopted].size} #{'file'.pluralize(result[:adopted].size)}."
        end

      redirect_to library_path(@library), notice: notice
    rescue Keepsake::Sweep::ReadOnly, Keepsake::StorageError => e
      redirect_to library_path(@library), alert: e.message
    end

    private
      def load_library
        @library = Current.user.libraries.find_by(id: params[:library_id])
        raise ActionController::RoutingError, "Not Found" unless @library&.viewable_by?(Current.user)
      end

      def ensure_writable
        return if @library.access_read_write?
        raise ActionController::RoutingError, "Not Found"
      end
  end
end
