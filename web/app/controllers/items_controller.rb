class ItemsController < ApplicationController
  def show
    library = Current.organization.libraries.find_by(id: params[:library_id])
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
    library = Current.organization.libraries.find_by(id: params[:library_id])
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

  # Ask the file itself for everything it can still tell us: the recording
  # date and runtime out of its own header, and a still if it has none.
  #
  # The sweep does this across a library; this is for the one video you are
  # looking at. Only fills what is absent -- nothing you typed is overwritten.
  def enrich
    library = Current.organization.libraries.find_by(id: params[:library_id])
    raise ActionController::RoutingError, "Not Found" unless library&.viewable_by?(Current.user)
    raise ActionController::RoutingError, "Not Found" unless library.access_read_write?

    item = library.catalog&.items&.find_by(id: params[:id])
    raise ActionController::RoutingError, "Not Found" unless item

    client = library.client
    sidecar = client.get_json(Keepsake::Media.sidecar_key_for(item.path))
    raise ActionController::RoutingError, "Not Found" if sidecar.nil?

    found = []
    additions = {}

    # Costs a couple of ranged reads. No decode, no download.
    header = Keepsake::MovieHeader.read(Keepsake::RangeReader.new(client, item.path))
    if header
      if sidecar["recorded_at"].blank? && header.recorded_at.present?
        additions["recorded_at"] = header.recorded_at
        found << "recorded #{header.recorded_at}"
      end
      if sidecar["duration_s"].blank? && header.duration_s.present?
        additions["duration_s"] = header.duration_s
        found << "#{header.duration_s.round}s long"
      end
    end

    if item.thumbnail_key.blank? && Keepsake::Media.video?(item.path)
      filename = Keepsake::Thumbnailer.new(client).call(item.path)
      if filename
        additions["thumbnail"] = filename
        found << "a thumbnail"
      end
    end

    if additions.empty?
      return redirect_to library_item_path(library, item),
        notice: header ? "Nothing further in the file." : "This file carries no readable metadata."
    end

    merged = Keepsake::Sidecar.fill_absent(sidecar, additions)
    client.put_json(Keepsake::Media.sidecar_key_for(item.path), merged)
    Keepsake::IndexBuilder.new(client).replace_entry(item.path, merged)

    item.update!(
      recorded_at: merged["recorded_at"],
      duration_s: merged["duration_s"],
      thumbnail: merged["thumbnail"],
      sidecar: merged
    )

    redirect_to library_item_path(library, item), notice: "Found #{found.to_sentence}."
  rescue Keepsake::StorageError => e
    redirect_to library_item_path(params[:library_id], params[:id]), alert: e.message
  end
end
