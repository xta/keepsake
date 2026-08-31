module Dev
  # Serves bytes for the local-directory backend, which exists so the app can
  # be developed and tested with no network and no credentials.
  #
  # Development and test only. In any other environment this route is not even
  # drawn, and the guard here is belt and braces.
  class MediaController < ApplicationController
    before_action :ensure_local_environment

    def show
      library = Current.user.libraries.find_by(id: params[:library_id])
      raise ActionController::RoutingError, "Not Found" unless library&.provider == "local"

      path = library.client.path_for(params[:key])
      raise ActionController::RoutingError, "Not Found" unless path.file?

      serve path
    rescue Keepsake::StorageError
      raise ActionController::RoutingError, "Not Found"
    end

    private
      def ensure_local_environment
        raise ActionController::RoutingError, "Not Found" unless Rails.env.local?
      end

      def serve(path)
        # Type comes from the extension, never from sniffing the file: that is
        # SPEC's rule, and it is why this does not use Marcel (which would also
        # drag in Active Storage).
        type = Keepsake::Media.mime_type(params[:key].to_s)
        disposition = params[:disposition].presence_in(%w[ attachment ]) || "inline"
        size = path.size

        # Range support is the whole reason this exists rather than a plain
        # send_file. A <video> element seeks by asking for byte ranges, and an
        # object store answers them natively -- so a dev backend that always
        # returns 200 would make seeking work in production and silently fail
        # in development, which is the wrong way round for a bug to hide.
        response.headers["Accept-Ranges"] = "bytes"
        range = parse_range(request.headers["Range"], size)

        if range
          response.headers["Content-Range"] = "bytes #{range.first}-#{range.last}/#{size}"
          send_data IO.binread(path, range.size, range.first),
                    type: type, disposition: disposition, status: :partial_content
        else
          send_file path, type: type, disposition: disposition
        end
      end

      # Only the single-range form, which is all any browser sends for media.
      def parse_range(header, size)
        return nil if header.blank? || size.zero?

        match = header.match(/\Abytes=(\d*)-(\d*)\z/)
        return nil unless match

        first, last = match[1], match[2]

        if first.empty?
          # "bytes=-500" means the final 500 bytes.
          return nil if last.empty?
          from = [ size - last.to_i, 0 ].max
          to = size - 1
        else
          from = first.to_i
          to = last.empty? ? size - 1 : [ last.to_i, size - 1 ].min
        end

        return nil if from > to || from >= size
        (from..to)
      end
  end
end
