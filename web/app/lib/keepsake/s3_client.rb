module Keepsake
  # Thin wrapper over aws-sdk-s3. Deliberately small: list, get, presign, head.
  #
  # Rails never proxies media bytes. Playback is a presigned URL handed to the
  # browser, so the video streams bucket-to-browser and no Puma thread is held
  # for the length of a film.
  class S3Client
    # SPEC reserves exactly one key at the bucket root.
    INDEX_KEY = "index.json".freeze

    # SigV4 checks expiry on EVERY request, and a <video> element issues range
    # requests across the whole watch. An hour would kill a 90-minute film at
    # the 60-minute mark and look like file corruption.
    MEDIA_EXPIRY = 12.hours
    THUMBNAIL_EXPIRY = 1.hour

    attr_reader :library

    def initialize(library)
      @library = library
    end

    def head_bucket
      client.head_bucket(bucket: library.bucket)
      true
    rescue Aws::Errors::ServiceError, Seahorse::Client::NetworkingError => e
      raise StorageError.new(readable(e), cause_class: e.class.name)
    end

    # Returns [parsed_json, etag], or [nil, etag] when the catalog has not
    # changed since `etag`. Raises CatalogMissing when there is no index.json,
    # which is a normal state for a bucket nobody has synced yet.
    def get_index(etag: nil)
      args = { bucket: library.bucket, key: key_for(INDEX_KEY) }
      args[:if_none_match] = etag if etag.present?

      response = client.get_object(**args)
      [ JSON.parse(response.body.read), response.etag ]
    rescue Aws::S3::Errors::NotModified
      [ nil, etag ]
    rescue Aws::S3::Errors::NoSuchKey, Aws::S3::Errors::NotFound
      raise CatalogMissing, "This bucket has no index.json yet."
    rescue JSON::ParserError => e
      raise StorageError.new("index.json is not valid JSON (#{e.message})")
    rescue Aws::Errors::ServiceError, Seahorse::Client::NetworkingError => e
      raise StorageError.new(readable(e), cause_class: e.class.name)
    end

    # Presigning is local HMAC -- no network call -- so a page of 200
    # thumbnails costs nothing extra. Generate at render time, never ahead.
    def presigned_url(key, expires_in: MEDIA_EXPIRY, disposition: nil)
      params = {
        bucket: library.bucket,
        key: key_for(key),
        expires_in: expires_in.to_i
      }
      # Cross-origin <a download> is ignored by every browser, so a plain link
      # to a presigned URL opens the file instead of saving it. Signing a
      # content-disposition is what actually makes a download button download.
      params[:response_content_disposition] = disposition if disposition.present?

      presigner.presigned_url(:get_object, **params)
    end

    def download_url(key)
      filename = key.to_s.split("/").last
      presigned_url(key, disposition: %(attachment; filename="#{filename}"))
    end

    def list_keys(limit: nil)
      keys = []
      client.list_objects_v2(bucket: library.bucket, prefix: library.prefix).each do |page|
        page.contents.each do |object|
          keys << { key: strip_prefix(object.key), size: object.size, last_modified: object.last_modified }
          return keys if limit && keys.size >= limit
        end
      end
      keys
    rescue Aws::Errors::ServiceError, Seahorse::Client::NetworkingError => e
      raise StorageError.new(readable(e), cause_class: e.class.name)
    end

    def key_for(path) = "#{library.prefix}#{path}"

    private
      def strip_prefix(key)
        library.prefix.present? ? key.delete_prefix(library.prefix) : key
      end

      def client
        @client ||= Aws::S3::Client.new(**client_options)
      rescue ArgumentError => e
        # The SDK raises a bare ArgumentError for things like a malformed
        # region. Left alone that is a 500 on the grid, which is both alarming
        # and useless -- the user cannot see which field is wrong, and the page
        # carrying the fix is the one that crashed.
        raise StorageError.new("This library is misconfigured: #{e.message}", cause_class: e.class.name)
      end

      def presigner
        @presigner ||= Aws::S3::Presigner.new(client: client)
      end

      def client_options
        # Re-validate at request time, not only on save. A DNS record that was
        # public when the library was created can point at 127.0.0.1 by now.
        EndpointGuard.validate!(library.endpoint)

        {
          endpoint: library.endpoint,
          region: library.region,
          access_key_id: library.access_key_id,
          secret_access_key: library.secret_access_key,
          force_path_style: library.force_path_style,
          retry_limit: 3,
          # Backblaze B2 rejects the checksum headers newer AWS SDKs send by
          # default ("Unsupported header ... received for this API call"), so
          # ask for them only where the operation actually requires them. This
          # is the same workaround the Python CLI carries.
          request_checksum_calculation: "when_required",
          response_checksum_validation: "when_required"
        }
      end

      # Provider errors are what the user needs to see on the settings page.
      # Translate the few that have a clear cause; pass the rest through rather
      # than inventing a friendlier fiction.
      def readable(error)
        case error
        when Aws::S3::Errors::NoSuchBucket
          "No bucket named #{library.bucket} at this endpoint."
        when Aws::S3::Errors::InvalidAccessKeyId
          "The access key id was not recognised."
        when Aws::S3::Errors::SignatureDoesNotMatch
          "The secret key did not match. Check for a copied space or a truncated value."
        when Aws::S3::Errors::AccessDenied, Aws::S3::Errors::Forbidden
          "Access denied. The key may lack list/read permission on this bucket."
        when Seahorse::Client::NetworkingError
          "Could not reach #{library.endpoint} (#{error.message})."
        else
          error.message.presence || error.class.name
        end
      end
  end
end
