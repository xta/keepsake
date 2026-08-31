module Keepsake
  # Classifies every key in a bucket, following SPEC.md's reindex rules in
  # order:
  #
  #   1. Sidecars.   Every key ending in .json. Stripping it gives the media key.
  #   2. Thumbnails. Every key formed by appending an image extension to another
  #                  key PRESENT IN THE BUCKET.
  #   3. Media.      Everything remaining that carries a file extension.
  #
  # Each step reads the set of keys present, not the results of the step
  # before it. That is what stops a bucket freshly filled by an upload tool
  # from counting derived files as library items.
  class Survey
    # SPEC reserves exactly one key at the bucket root.
    INDEX_KEY = "index.json".freeze

    attr_reader :media, :sidecars, :thumbnails, :sizes, :timestamps,
                :orphan_sidecars, :without_extension, :case_collisions

    def initialize(entries)
      @entries = entries.reject { |e| e[:key] == INDEX_KEY }
      @sizes = {}
      @timestamps = {}
      classify
    end

    def self.call(client) = new(client.list_keys)

    # Media with no sidecar. SPEC: "Surface it, don't hide it." These are what
    # a sweep adopts.
    def unindexed = @media.reject { |key| @sidecars.key?(key) }

    def indexed = @media.select { |key| @sidecars.key?(key) }

    # Everything worth telling a person about, without stopping the job.
    def problems
      list = []
      @orphan_sidecars.each do |key|
        list << { kind: "sidecar_without_media", key: key,
                  detail: "Describes a file that is not in the bucket." }
      end
      @without_extension.each do |key|
        list << { kind: "no_extension", key: key,
                  detail: "Not catalogued: keepsake identifies media by its extension." }
      end
      @case_collisions.each do |group|
        list << { kind: "case_collision", key: group.first,
                  detail: "Differs only in case from #{(group - [ group.first ]).join(', ')}." }
      end
      list
    end

    private
      def classify
        keys = @entries.map { |e| e[:key] }
        present = keys.to_set

        @entries.each do |entry|
          @sizes[entry[:key]] = entry[:size]
          @timestamps[entry[:key]] = entry[:last_modified]
        end

        # 1. Sidecars.
        @sidecars = {}
        @orphan_sidecars = []
        keys.select { |k| Media.sidecar?(k) }.each do |key|
          media_key = Media.media_key_for_sidecar(key)
          if present.include?(media_key)
            @sidecars[media_key] = key
          else
            # SPEC: "Should be unreachable under the write order." Report it.
            @orphan_sidecars << key
          end
        end

        # 2. Thumbnails -- decided against the whole key set, so a thumbnail is
        #    recognised before its media has a sidecar.
        @thumbnails = {}
        keys.each do |key|
          owner = Media.thumbnail_of(key, present)
          @thumbnails[owner] = key if owner
        end

        companions = @sidecars.values.to_set + @thumbnails.values.to_set

        # 3. Media: everything left that carries an extension.
        remaining = keys.reject { |k| companions.include?(k) }
        @media = remaining.select { |k| Media.has_extension?(k) }.sort
        @without_extension = remaining.reject { |k| Media.has_extension?(k) }.sort

        # SPEC: a library must not contain two keys differing only in case --
        # no filesystem it is likely to be copied to can represent both.
        @case_collisions = keys.group_by(&:downcase).values.select { |g| g.size > 1 }
      end
  end
end
