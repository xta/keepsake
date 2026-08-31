module Keepsake
  # Fetches index.json and refreshes the cached catalog for one library.
  #
  # SPEC: "Each entry is the complete sidecar plus a `path` field giving the
  # media file's full key from the bucket root. Sidecar contents are inlined
  # rather than referenced so a viewer needs exactly one fetch to render a
  # library." That is why this reads the catalog and never lists the bucket:
  # listing plus N sidecar GETs is the same data for N+1 round trips.
  class CatalogSync
    attr_reader :library

    def initialize(library)
      @library = library
    end

    # Returns the Catalog. Raises CatalogMissing when the bucket has no
    # index.json, which is an ordinary state, not a failure.
    def call(force: false)
      catalog = library.catalog

      if catalog && !force && !catalog.stale?
        return catalog
      end

      document, etag = library.client.get_index(etag: force ? nil : catalog&.etag)

      if document.nil? && catalog
        # 304: the catalog we already hold is current. Cheapest possible
        # refresh -- one conditional request, no parsing, no writes but a
        # timestamp.
        catalog.update!(fetched_at: Time.current, etag: etag)
        return catalog
      end

      write(document, etag)
    end

    private
      def write(document, etag)
        items = Array(document["items"])

        Catalog.transaction do
          catalog = library.catalog || library.build_catalog
          catalog.assign_attributes(
            generated_at: parse_time(document["generated_at"]),
            # `count` is advisory; what we actually hold is what we parsed.
            item_count: items.size,
            total_bytes: items.sum { |i| i["size_bytes"].to_i },
            etag: etag,
            fetched_at: Time.current
          )
          catalog.save!

          # Replace wholesale rather than diffing. The catalog is derived and
          # disposable, the documents are small enough that a diff buys
          # nothing, and a replace cannot leave a half-merged cache behind.
          catalog.items.delete_all
          CatalogItem.insert_all!(rows_for(catalog, items)) if items.any?

          catalog.reload
        end
      end

      def rows_for(catalog, items)
        now = Time.current

        items.filter_map do |item|
          path = item["path"].presence
          next if path.blank?

          {
            catalog_id: catalog.id,
            path: path,
            # SPEC: the sidecar id is opaque. Stored for identity, never parsed.
            sidecar_id: item["id"],
            title: item["title"].presence,
            # Kept as text. SPEC allows a date or a full timestamp and the
            # difference is real information.
            recorded_at: item["recorded_at"].presence,
            uploaded_at: parse_time(item["uploaded_at"]),
            duration_s: item["duration_s"],
            size_bytes: item["size_bytes"],
            media_type: item["media_type"].presence,
            thumbnail: item["thumbnail"].presence,
            # The complete sidecar, verbatim. SPEC requires unknown fields to
            # survive a round trip, so this cache must not be where one gets
            # dropped.
            sidecar: item,
            created_at: now,
            updated_at: now
          }
        end
      end

      def parse_time(value)
        return nil if value.blank?
        Time.zone.parse(value.to_s)
      rescue ArgumentError
        nil
      end
  end
end
