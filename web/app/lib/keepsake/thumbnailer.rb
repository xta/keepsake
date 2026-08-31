module Keepsake
  # Generates a still for a video and stores it as its thumbnail companion.
  #
  # ffmpeg reads the video over a presigned URL and seeks, so it fetches the
  # header and the frames around the seek point rather than downloading the
  # file. A 4GB video costs a few megabytes of transfer, not four gigabytes.
  #
  # Failure is never fatal. SPEC makes thumbnails optional and derived: losing
  # one costs a re-render, not information, so anything unreadable is reported
  # and stepped over.
  class Thumbnailer
    # Far enough in to miss a black first frame, which phones and cameras
    # produce constantly.
    DEFAULT_SEEK = 5.0
    # A 4K still is roughly fifteen times the bytes for no gain in a grid cell.
    DEFAULT_WIDTH = 640
    # A frame decode that has not finished by now is not going to.
    TIMEOUT = 120

    class MissingFfmpeg < StorageError; end

    attr_reader :client

    def initialize(client, width: DEFAULT_WIDTH, seek: DEFAULT_SEEK)
      @client = client
      @width = width
      @seek = seek
    end

    def self.available?
      @available = system("ffmpeg", "-version", out: File::NULL, err: File::NULL) if @available.nil?
      @available
    end

    # Returns the thumbnail's filename (relative to the media file's own
    # directory, which is how SPEC records it) or nil if nothing could be made.
    def call(media_key)
      # Images are skipped. A phone library is mostly HEIC, which ffmpeg will
      # not reliably decode, and an image already renders in a grid on its own.
      return nil unless Media.video?(media_key)
      raise MissingFfmpeg, "ffmpeg is not installed on the server." unless self.class.available?

      source = client.readable_source(media_key)

      jpeg = render(source, @seek)
      # A clip shorter than the seek point yields no frame at all, which is
      # common enough in a phone library to be a normal case rather than an
      # error.
      jpeg = render(source, 0) if jpeg.blank?
      return nil if jpeg.blank?

      key = "#{media_key}.jpg"
      client.put_binary(key, jpeg, content_type: "image/jpeg")
      key.split("/").last
    end

    private
      def render(source, seek)
        Tempfile.create([ "keepsake-thumb", ".jpg" ]) do |file|
          file.close
          args = [
            "ffmpeg", "-nostdin", "-loglevel", "error", "-y",
            "-ss", seek.to_s,
            "-i", source,
            "-frames:v", "1",
            # Never upscale: a small source stays its own size.
            "-vf", "scale=w=min(#{@width}\\,iw):h=-2",
            file.path
          ]

          ok = run(args)
          return nil unless ok

          data = File.binread(file.path)
          data.presence
        end
      end

      # Arguments as an array, never a shell string: the URL and key come from
      # user-supplied configuration.
      def run(args)
        pid = Process.spawn(*args, out: File::NULL, err: File::NULL)
        deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + TIMEOUT

        loop do
          finished, status = Process.waitpid2(pid, Process::WNOHANG)
          return status.success? if finished

          if Process.clock_gettime(Process::CLOCK_MONOTONIC) > deadline
            Process.kill("KILL", pid)
            Process.waitpid(pid)
            return false
          end
          sleep 0.1
        end
      rescue Errno::ENOENT
        raise MissingFfmpeg, "ffmpeg is not installed on the server."
      end
  end
end
