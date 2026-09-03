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
      redirect_to edit_library_path(@library, from: params[:from]), alert: e.message
    end

    def create
      return redirect_to(edit_library_path(@library, from: params[:from]), alert: "A scan is already running.") if @library.sweeping?

      # Enqueued, not run here: reading every sidecar and decoding a frame per
      # video will outlast any request.
      SweepJob.perform_later(@library)
      @library.update!(sweep_state: "running", sweep_message: "Queued", sweep_started_at: Time.current)

      redirect_to edit_library_path(@library, from: params[:from]), notice: "Scanning. This page will keep you posted."
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
