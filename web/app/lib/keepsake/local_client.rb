module Keepsake
  # A directory standing in for a bucket.
  #
  # Exists so the whole app is developable and testable with no network and no
  # credentials -- the same reason the Python CLI carries `LocalDirBucket`. It
  # implements the S3Client interface exactly, which is also a small proof that
  # nothing above the storage layer knows which backend it is talking to.
  #
  # Development and test only; `Library` refuses to save a local provider
  # anywhere else.
  class LocalClient
    INDEX_KEY = S3Client::INDEX_KEY
    MEDIA_EXPIRY = S3Client::MEDIA_EXPIRY
    THUMBNAIL_EXPIRY = S3Client::THUMBNAIL_EXPIRY

    attr_reader :library

    def initialize(library)
      @library = library
    end

    def root = Pathname.new(library.bucket)

    def head_bucket
      unless root.directory?
        raise StorageError, "No directory at #{root}."
      end
      true
    end

    def get_index(etag: nil)
      path = path_for(INDEX_KEY)
      raise CatalogMissing, "No index.json in #{root}." unless path.file?

      body = path.read
      # Mtime plus size is a perfectly good ETag for a local file, and it lets
      # the conditional-refetch path be exercised offline.
      current = %("#{path.mtime.to_i}-#{path.size}")
      return [ nil, current ] if etag.present? && etag == current

      [ JSON.parse(body), current ]
    rescue JSON::ParserError => e
      raise StorageError.new("index.json is not valid JSON (#{e.message})")
    end

    # There is nothing to sign, but the caller still needs a URL a browser can
    # fetch. A development-only route serves the bytes.
    def presigned_url(key, expires_in: MEDIA_EXPIRY, disposition: nil)
      query = { key: key }
      query[:disposition] = "attachment" if disposition.present?
      "/dev/media/#{library.id}?#{query.to_query}"
    end

    def download_url(key) = presigned_url(key, disposition: "attachment")

    def list_keys(limit: nil)
      return [] unless root.directory?

      base = library.prefix.present? ? root.join(library.prefix) : root
      return [] unless base.directory?

      keys = []
      base.glob("**/*").sort.each do |path|
        next unless path.file?
        keys << {
          key: path.relative_path_from(base).to_s,
          size: path.size,
          last_modified: path.mtime
        }
        break if limit && keys.size >= limit
      end
      keys
    end

    def get_json(key)
      path = path_for(key)
      return nil unless path.file?
      JSON.parse(path.read)
    rescue JSON::ParserError => e
      raise StorageError.new("#{key} is not valid JSON (#{e.message})")
    end

    def put_json(key, document)
      path = path_for(key)
      path.dirname.mkpath
      path.write(JSON.pretty_generate(document) + "\n")
      true
    end

    # `presigned_url` returns a route this app serves, which is right for a
    # browser and useless to a subprocess. ffmpeg gets the file itself.
    def readable_source(key) = "file://#{path_for(key)}"

    def put_binary(key, data, content_type: nil)
      path = path_for(key)
      path.dirname.mkpath
      path.binwrite(data)
      true
    end

    def object_size(key)
      path = path_for(key)
      path.file? ? path.size : nil
    end

    def get_range(key, first, last)
      path = path_for(key)
      return nil unless path.file?
      IO.binread(path, last - first + 1, first)
    end

    def key_for(path) = "#{library.prefix}#{path}"

    # Resolves a key to a real file, refusing anything that escapes the root.
    # The dev media route hands user input straight in here.
    def path_for(key)
      candidate = root.join(library.prefix.to_s, key.to_s).cleanpath
      unless candidate.to_s == root.cleanpath.to_s || candidate.to_s.start_with?("#{root.cleanpath}/")
        raise StorageError, "Key escapes the library root."
      end
      candidate
    end
  end
end
