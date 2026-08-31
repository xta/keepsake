module Keepsake
  # A movie's recording date and runtime, read from its own header.
  #
  # MP4 and QuickTime both keep the two facts most worth having -- when the
  # camera started recording, and how long the result runs -- in a small `mvhd`
  # box. No ffmpeg, no transcode, no download: a couple of ranged reads and a
  # few hundred bytes.
  #
  # Written from the ISO base media format layout, and it never raises. A file
  # that is not one, or is truncated, or was written by something creative,
  # returns nil. An absent date is a state the archive already understands, and
  # a parser that halted a sweep over an unreadable header would be worse than
  # no parser at all.
  class MovieHeader
    # mvhd timestamps count seconds from 1904-01-01, not the Unix epoch.
    QUICKTIME_EPOCH = Time.utc(1904, 1, 1).freeze

    # A malformed size field could otherwise walk forever.
    MAX_BOXES = 128

    # What mvhd writes when it does not know the duration.
    UNKNOWN_DURATION = 0xFFFFFFFF

    # `duration / timescale` is a ratio of two integers -- 109064/600 -- and
    # storing it raw puts seventeen digits of float noise into an archive meant
    # to outlive its tools. A millisecond is finer than anything anyone will
    # ask of a home video.
    DURATION_PLACES = 3

    attr_reader :recorded_at, :duration_s

    def initialize(recorded_at: nil, duration_s: nil)
      @recorded_at = recorded_at
      @duration_s = duration_s
    end

    def present? = recorded_at.present? || duration_s.present?

    def self.read(reader)
      return nil if reader.nil? || reader.size.nil? || reader.size.zero?

      moov = find(reader, 0, reader.size, "moov")
      return nil if moov.nil?

      mvhd = find(reader, moov[0], moov[1], "mvhd")
      return nil if mvhd.nil?

      payload = reader.read(mvhd[0], [ mvhd[1] - mvhd[0], 128 ].min)
      return nil if payload.nil? || payload.bytesize < 20

      header = parse(payload)
      header.present? ? header : nil
    rescue StandardError
      # Deliberately broad. Nothing about an odd file should stop a sweep.
      nil
    end

    # Box layout is `size(4) type(4)`, where size counts the header. A size of
    # 1 means a real 64-bit size follows the type; 0 means "to the end".
    def self.each_box(reader, start, finish)
      position = start
      MAX_BOXES.times do
        break if position + 8 > finish

        header = reader.read(position, 8)
        break if header.nil? || header.bytesize < 8

        size, kind = header.unpack("Na4")
        body = position + 8

        if size == 1
          extra = reader.read(position + 8, 8)
          break if extra.nil? || extra.bytesize < 8
          size = extra.unpack1("Q>")
          body = position + 16
        elsif size.zero?
          size = finish - position
        end

        stop = position + size
        break if size < 8 || stop > finish

        yield kind, body, stop
        position = stop
      end
    end

    def self.find(reader, start, finish, wanted)
      each_box(reader, start, finish) do |kind, body, stop|
        return [ body, stop ] if kind == wanted
      end
      nil
    end

    def self.parse(payload)
      version = payload.getbyte(0)

      if version == 1
        creation = payload.byteslice(4, 8).unpack1("Q>")
        timescale = payload.byteslice(20, 4).unpack1("N")
        duration = payload.byteslice(24, 8).unpack1("Q>")
        needed = 32
      else
        creation = payload.byteslice(4, 4).unpack1("N")
        timescale = payload.byteslice(12, 4).unpack1("N")
        duration = payload.byteslice(16, 4).unpack1("N")
        needed = 20
      end
      return new if payload.bytesize < needed

      runtime = nil
      if timescale.to_i.positive? && duration.to_i.positive? && duration != UNKNOWN_DURATION
        runtime = (duration.to_f / timescale).round(DURATION_PLACES)
        runtime = nil if runtime.zero?
      end

      new(recorded_at: creation_date(creation), duration_s: runtime)
    end

    # Date only, deliberately. Apple writes this field as local wall-clock time
    # with no zone attached, so treating it as UTC would shift a late-evening
    # recording onto the wrong day -- and would look precise while doing it. A
    # date is the most that is actually known.
    def self.creation_date(seconds)
      return nil if seconds.nil? || seconds <= 0

      moment = QUICKTIME_EPOCH + seconds
      # A stamp in the future is a broken clock or a misparse, not a fact.
      return nil if moment > Time.current + 1.day

      moment.utc.strftime("%Y-%m-%d")
    rescue RangeError, FloatDomainError
      nil
    end
  end
end
