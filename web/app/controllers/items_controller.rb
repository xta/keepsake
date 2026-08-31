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
end
