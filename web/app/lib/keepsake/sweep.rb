module Keepsake
  # Brings a bucket up to date with the convention, in four passes.
  #
  #   1. Adopt      media that has no sidecar (arrived via a phone app, say).
  #   2. Backfill   recorded_at and duration_s from each movie's own header.
  #   3. Thumbnail  any video that has no thumbnail companion.
  #   4. Reindex    rebuild index.json from what is now in the bucket.
  #
  # Every pass only ever ADDS what is absent. Nothing overwrites a sidecar, a
  # media file, a thumbnail that exists, or a field somebody typed.
  class Sweep
    class ReadOnly < StorageError; end

    attr_reader :library, :log

    def initialize(library, thumbnails: true)
      @library = library
      @thumbnails = thumbnails
      @log = []
    end

    # Cheap: one listing, no object reads. Backfill is not previewed because
    # deciding whether a field is absent means reading every sidecar, and a
    # preview should not cost as much as the job.
    def plan
      survey = Survey.call(client)

      {
        adoptable: survey.unindexed.map { |key| describe(key, survey) },
        missing_thumbnails: thumbnailable(survey).size,
        already_indexed: survey.indexed.size,
        problems: survey.problems,
        survey: survey
      }
    end

    def apply(progress: nil)
      ensure_writable!
      survey = Survey.call(client)

      adopted = adopt(survey, progress)
      # Re-survey: the files just adopted now have sidecars to backfill into.
      survey = Survey.call(client)
      filled = backfill(survey, progress)
      thumbed = @thumbnails ? generate_thumbnails(survey, progress) : []

      progress&.call("Rebuilding the catalog")
      document = IndexBuilder.new(client).call

      {
        adopted: adopted, backfilled: filled, thumbnailed: thumbed,
        count: document["count"], problems: survey.problems, log: @log
      }
    end

    private
      def client = @client ||= library.client

      def ensure_writable!
        return if library.access_read_write?
        raise ReadOnly, "This library is set to read-only."
      end

      def adopt(survey, progress)
        survey.unindexed.filter_map do |media_key|
          sidecar_key = Media.sidecar_key_for(media_key)
          # Re-checked at write time: a sidecar that appeared since the survey
          # belongs to whoever wrote it.
          next if client.get_json(sidecar_key).present?

          progress&.call("Adopting #{media_key}")
          client.put_json(sidecar_key, Sidecar.build_stub(
            media_key,
            size_bytes: survey.sizes[media_key],
            last_modified: survey.timestamps[media_key]
          ))
          media_key
        end
      end

      # Reads each movie's own header over byte ranges: a couple of requests
      # and a few hundred bytes per file, no decode and no download.
      def backfill(survey, progress)
        survey.indexed.filter_map do |media_key|
          next unless Media.video?(media_key)

          sidecar_key = survey.sidecars.fetch(media_key)
          sidecar = client.get_json(sidecar_key)
          next if sidecar.nil?
          next if sidecar["recorded_at"].present? && sidecar["duration_s"].present?

          progress&.call("Reading #{media_key}")
          header = MovieHeader.read(RangeReader.new(client, media_key, size: survey.sizes[media_key]))
          next if header.nil?

          # Only absent fields: a date somebody typed outranks one from a header.
          merged = Sidecar.fill_absent(sidecar, {
            "recorded_at" => header.recorded_at,
            "duration_s" => header.duration_s
          })
          next if merged == sidecar

          client.put_json(sidecar_key, merged)
          media_key
        end
      end

      def thumbnailable(survey)
        survey.media.select do |key|
          Media.video?(key) && !survey.thumbnails.key?(key)
        end
      end

      def generate_thumbnails(survey, progress)
        candidates = thumbnailable(survey)
        return [] if candidates.empty?

        thumbnailer = Thumbnailer.new(client)

        candidates.filter_map do |media_key|
          progress&.call("Rendering a still for #{media_key}")
          filename = thumbnailer.call(media_key)
          next if filename.nil?

          # The sidecar records which extension exists, so a client reading
          # index.json does not have to probe for it.
          sidecar_key = survey.sidecars[media_key]
          if sidecar_key && (sidecar = client.get_json(sidecar_key))
            client.put_json(sidecar_key, Sidecar.fill_absent(sidecar, { "thumbnail" => filename }))
          end
          media_key
        rescue Thumbnailer::MissingFfmpeg => e
          @log << e.message
          # No point trying the rest; the tool is simply not there.
          break
        rescue StorageError => e
          # SPEC: thumbnails are optional and derived. Report and carry on.
          @log << "#{media_key}: #{e.message}"
          next
        end
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
