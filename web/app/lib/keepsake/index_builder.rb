module Keepsake
  # Rebuilds index.json from what is actually in the bucket.
  #
  # SPEC: the catalog is derived and disposable. "index.json contains no
  # information that is not derivable from the bucket. Delete it, reindex, and
  # nothing is lost."
  class IndexBuilder
    def initialize(client)
      @client = client
    end

    # Reads every sidecar. That is one request per catalogued file, which is
    # the cost of a full rebuild -- and why SPEC says full rebuilds are for
    # repair rather than for every write.
    def call(survey = nil)
      survey ||= Survey.call(@client)

      items = survey.indexed.filter_map do |media_key|
        sidecar = @client.get_json(survey.sidecars.fetch(media_key))
        next if sidecar.nil?
        # SPEC: "Each entry is the complete sidecar plus a `path` field giving
        # the media file's full key from the bucket root." Inlined, so a viewer
        # needs exactly one fetch.
        sidecar.merge("path" => media_key)
      end

      # SPEC: "items is sorted by path, ascending. This is a stability
      # guarantee, not a display order." It keeps rebuilds byte-stable.
      items.sort_by! { |item| item["path"] }

      document = {
        "generated_at" => Sidecar.rfc3339(Time.current),
        "count" => items.size,
        "items" => items
      }

      @client.put_json(Survey::INDEX_KEY, document)
      document
    end

    # SPEC's incremental path: "A writer that trusts the current index.json may
    # insert, replace, or remove a single entry at its sorted position and
    # update generated_at and count."
    #
    # A title edit should not cost one request per file in the library. Falls
    # back to a full rebuild when there is no catalog to amend.
    def replace_entry(media_key, sidecar)
      document = @client.get_json(Survey::INDEX_KEY)
      return call if document.nil? || !document["items"].is_a?(Array)

      items = document["items"].reject { |item| item["path"] == media_key }
      items << sidecar.merge("path" => media_key)
      items.sort_by! { |item| item["path"] }

      document["items"] = items
      document["count"] = items.size
      document["generated_at"] = Sidecar.rfc3339(Time.current)

      @client.put_json(Survey::INDEX_KEY, document)
      document
    end
  end
end
