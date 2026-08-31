module Keepsake
  # A seekable window onto a remote object, backed by byte-range requests.
  #
  # Exists so a parser can walk a file's box structure without downloading it.
  # Reads are served from whole chunks and cached, so walking a header costs a
  # couple of requests rather than one per field -- measured at two for a movie
  # with its `moov` box at the end, which is the common case.
  class RangeReader
    CHUNK = 64 * 1024

    attr_reader :size

    def initialize(client, key, size: nil)
      @client = client
      @key = key
      @size = size || client.object_size(key)
      @chunks = {}
    end

    def read(offset, length)
      return nil if @size.nil? || offset >= @size
      length = [ length, @size - offset ].min
      return "" if length <= 0

      out = +""
      position = offset
      while out.bytesize < length
        chunk_index = position / CHUNK
        chunk = chunk_at(chunk_index)
        return nil if chunk.nil? || chunk.empty?

        within = position - (chunk_index * CHUNK)
        slice = chunk.byteslice(within, length - out.bytesize)
        return nil if slice.nil? || slice.empty?

        out << slice
        position += slice.bytesize
      end
      out
    end

    def requests = @requests.to_i

    private
      def chunk_at(index)
        @chunks[index] ||= begin
          first = index * CHUNK
          last = [ first + CHUNK - 1, @size - 1 ].min
          @requests = @requests.to_i + 1
          @client.get_range(@key, first, last)
        end
      end
  end
end
