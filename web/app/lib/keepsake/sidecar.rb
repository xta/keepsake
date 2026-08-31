module Keepsake
  # Building and merging sidecars, per SPEC.md.
  module Sidecar
    module_function

    SCHEMA_VERSION = 1

    # Fields this app understands. Anything else a sidecar carries is preserved
    # untouched -- SPEC requires a writer that does not recognise a field to
    # carry it through unchanged, so clients of different versions can coexist.
    KNOWN_FIELDS = %w[
      schema id file title recorded_at uploaded_at tags location notes
      duration_s size_bytes media_type sha256 thumbnail
    ].freeze

    # A stub for media that has none. Records ONLY what the bucket already
    # knows for certain: identity, the file's own name, when it landed, its
    # size, its type.
    #
    # `title` and `recorded_at` are deliberately ABSENT rather than guessed. A
    # path like 2026/05/IMG_0002.MOV implies a year and a month, but SPEC wants
    # YYYY-MM-DD, and inventing a day would put a fact in the archive that
    # nobody established. An absent field is honest and easy to fill in later;
    # a wrong one looks authoritative forever. A placeholder title would be the
    # same mistake with a friendlier face.
    def build_stub(media_key, size_bytes: nil, last_modified: nil)
      {
        "schema" => SCHEMA_VERSION,
        "id" => generate_id,
        "file" => media_key.to_s.split("/").last,
        "uploaded_at" => rfc3339(last_modified || Time.current)
      }.tap do |sidecar|
        sidecar["size_bytes"] = size_bytes if size_bytes
        type = Media.mime_type(media_key)
        sidecar["media_type"] = type if type.present? && type != "application/octet-stream"
      end
    end

    # SPEC recommends UUIDv7: time-ordered, so sidecars sort roughly by
    # creation. Readers must not parse it, so the only real requirement is
    # uniqueness.
    def generate_id
      if SecureRandom.respond_to?(:uuid_v7)
        SecureRandom.uuid_v7
      else
        SecureRandom.uuid
      end
    end

    def rfc3339(moment) = moment.utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    # SPEC's concurrency rule, and the reason this takes a `current` rather
    # than a sidecar loaded earlier:
    #
    #   "A client that loads a sidecar, waits while someone types, then PUTs
    #    will clobber anything written in between. Writers should therefore
    #    re-read the sidecar immediately before writing and merge field-by-field."
    #
    # The unsafe window becomes one request rather than a whole edit session.
    # It does not close entirely, and for a family archive that is the accepted
    # trade: a lost edit costs a retyped title, not a video.
    def merge(current, changes)
      merged = (current || {}).dup

      changes.each do |field, value|
        if value.nil? || (value.respond_to?(:empty?) && value.empty?)
          # Clearing a field removes it rather than storing an empty string.
          # SPEC's optional fields are absent-or-meaningful; "" is neither.
          merged.delete(field.to_s)
        else
          merged[field.to_s] = value
        end
      end

      merged["schema"] ||= SCHEMA_VERSION
      merged
    end

    # Read the sidecar as it is right now, apply changes, write it back.
    def update!(client, media_key, changes)
      key = Media.sidecar_key_for(media_key)
      current = client.get_json(key)
      raise StorageError, "No sidecar at #{key}." if current.nil?

      merged = merge(current, changes)
      client.put_json(key, merged)
      merged
    end
  end
end
