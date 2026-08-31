class ItemsController < ApplicationController
  def show
    library = Current.user.libraries.find_by(id: params[:library_id])
    raise ActionController::RoutingError, "Not Found" unless library&.viewable_by?(Current.user)

    catalog = library.catalog
    item = catalog&.items&.find_by(id: params[:id])
    raise ActionController::RoutingError, "Not Found" unless item

    client = library.client
    ordered = catalog.items.newest_first.pluck(:id)
    position = ordered.index(item.id)

    render inertia: "items/show", props: {
      library: LibrarySerializer.call(library),
      item: CatalogItemSerializer.call(item, client: client, media: true),
      prevId: position && position > 0 ? ordered[position - 1] : nil,
      nextId: position ? ordered[position + 1] : nil
    }
  end

  # Editing metadata writes to the bucket, because the bucket is the source of
  # truth. The local row is a cache, updated afterwards.
  def update
    library = Current.user.libraries.find_by(id: params[:library_id])
    raise ActionController::RoutingError, "Not Found" unless library&.viewable_by?(Current.user)
    # Hidden, not merely refused, on a read-only library.
    raise ActionController::RoutingError, "Not Found" unless library.access_read_write?

    item = library.catalog&.items&.find_by(id: params[:id])
    raise ActionController::RoutingError, "Not Found" unless item

    changes = {
      "title" => params[:title].to_s.strip,
      "recorded_at" => params[:recorded_at].to_s.strip,
      "location" => params[:location].to_s.strip,
      "notes" => params[:notes].to_s.strip
    }

    # Sidecar.update! re-reads immediately before writing and merges field by
    # field. That is SPEC's rule: PUTting an object loaded when the page
    # rendered would clobber anything written while the form sat open.
    merged = Keepsake::Sidecar.update!(library.client, item.path, changes)

    # SPEC allows amending index.json in place rather than rebuilding it, which
    # keeps a title edit at two requests instead of one per file in the library.
    Keepsake::IndexBuilder.new(library.client).replace_entry(item.path, merged)

    # Only the columns the cache actually has. Everything else -- location,
    # notes, and any field another client invented -- lives in `sidecar`, which
    # is stored whole and is what the detail page reads.
    item.update!(
      title: merged["title"],
      recorded_at: merged["recorded_at"],
      sidecar: merged
    )

    redirect_to library_item_path(library, item), notice: "Saved."
  rescue Keepsake::StorageError => e
    redirect_to library_item_path(params[:library_id], params[:id]), alert: e.message
  end

  # Regenerate a still for one file. The sweep does this in bulk; this is for
  # the single video you are looking at that has not got one.
  def thumbnail
    library = Current.user.libraries.find_by(id: params[:library_id])
    raise ActionController::RoutingError, "Not Found" unless library&.viewable_by?(Current.user)
    raise ActionController::RoutingError, "Not Found" unless library.access_read_write?

    item = library.catalog&.items&.find_by(id: params[:id])
    raise ActionController::RoutingError, "Not Found" unless item

    filename = Keepsake::Thumbnailer.new(library.client).call(item.path)
    if filename.nil?
      return redirect_to library_item_path(library, item),
        alert: "Could not render a still from this file."
    end

    merged = Keepsake::Sidecar.update!(library.client, item.path, { "thumbnail" => filename })
    Keepsake::IndexBuilder.new(library.client).replace_entry(item.path, merged)
    item.update!(thumbnail: filename, sidecar: merged)

    redirect_to library_item_path(library, item), notice: "Thumbnail created."
  rescue Keepsake::StorageError => e
    redirect_to library_item_path(params[:library_id], params[:id]), alert: e.message
  end
end
