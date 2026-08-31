module Keepsake
  # Adopts media that arrived by some other route -- a phone upload app, a
  # desktop client, anything that puts files in the bucket without writing
  # keepsake's metadata.
  #
  # Two phases, always. `plan` reads and reports; `apply` writes. Nothing is
  # written that was not shown first.
  #
  # What it will do:  create a sidecar for media that has none, then rebuild
  #                   index.json.
  # What it will NOT do: overwrite an existing sidecar, touch a media file,
  #                   delete anything, or guess a title or a date.
  class Sweep
    class ReadOnly < StorageError; end

    attr_reader :library

    def initialize(library)
      @library = library
    end

    def plan
      survey = Survey.call(client)

      {
        adoptable: survey.unindexed.map { |key| describe(key, survey) },
        already_indexed: survey.indexed.size,
        problems: survey.problems,
        survey: survey
      }
    end

    def apply
      ensure_writable!

      result = plan
      survey = result[:survey]
      written = []

      survey.unindexed.each do |media_key|
        sidecar_key = Media.sidecar_key_for(media_key)

        # Never overwrite. A sidecar that appeared since the plan was made
        # belongs to whoever wrote it, and it is the source of truth.
        next if client.get_json(sidecar_key).present?

        client.put_json(sidecar_key, Sidecar.build_stub(
          media_key,
          size_bytes: survey.sizes[media_key],
          last_modified: survey.timestamps[media_key]
        ))
        written << media_key
      end

      # Rebuild from the bucket rather than from the plan, so anything another
      # client wrote in the meantime is picked up too.
      document = IndexBuilder.new(client).call

      { adopted: written, count: document["count"], problems: result[:problems] }
    end

    private
      def client = @client ||= library.client

      def ensure_writable!
        return if library.access_read_write?
        raise ReadOnly, "This library is set to read-only."
      end

      def describe(media_key, survey)
        {
          path: media_key,
          size_bytes: survey.sizes[media_key],
          last_modified: survey.timestamps[media_key]&.iso8601,
          has_thumbnail: survey.thumbnails.key?(media_key),
          kind: Media.kind(media_key)
        }
      end
  end
end
