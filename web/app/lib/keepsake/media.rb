module Keepsake
  # Key classification, straight from SPEC.md.
  #
  # "A reader must never inspect file contents to determine format. The
  # extension is the answer." Nothing in here opens a file.
  module Media
    module_function

    VIDEO_EXTS = %w[.mov .mp4 .m4v .avi .mkv .mpg .mpeg .wmv .3gp .webm .mts .m2ts .flv .ogv].freeze
    IMAGE_EXTS = %w[.jpg .jpeg .png .heic .heif .gif .webp .tif .tiff].freeze
    AUDIO_EXTS = %w[.mp3 .m4a .wav .aac .flac .aiff].freeze
    MEDIA_EXTS = (VIDEO_EXTS + IMAGE_EXTS + AUDIO_EXTS).freeze

    # Extensions a thumbnail may carry. SPEC: "{filename}.jpg (or .png, .webp)".
    THUMBNAIL_EXTS = %w[.jpg .jpeg .png .webp].freeze

    # Formats no mainstream browser will render, so never build a player for
    # them. This is half the detection; the other half is a runtime `error`
    # handler on the element, because codec support inside a container varies
    # by browser and no static table can know it.
    UNPLAYABLE_EXTS = %w[
      .heic .heif .tif .tiff
      .avi .wmv .mkv .mpg .mpeg .flv .mts .m2ts .3gp
    ].freeze

    # SPEC: "A key is media only when its final path segment does not begin
    # with `.` and contains a `.`". The leading dot outranks the extension, so
    # `.hidden.mp4` is not media.
    def has_extension?(key)
      segment = key.to_s.split("/").last.to_s
      return false if segment.start_with?(".")
      segment.include?(".")
    end

    # The key's extension, lowercased and including the dot, or "" when SPEC
    # says it has none. "Suffix case is insignificant."
    def extension_of(key)
      return "" unless has_extension?(key)
      ".#{key.to_s.split('/').last.split('.').last.downcase}"
    end

    def kind(key)
      case extension_of(key)
      when *VIDEO_EXTS then :video
      when *IMAGE_EXTS then :image
      when *AUDIO_EXTS then :audio
      else :other
      end
    end

    def video?(key) = kind(key) == :video
    def image?(key) = kind(key) == :image

    # Whether it is worth handing this key to a <video> or <img> element at
    # all. False means render the download card immediately.
    def playable?(key)
      return false unless has_extension?(key)
      return false if UNPLAYABLE_EXTS.include?(extension_of(key))
      %i[video image audio].include?(kind(key))
    end

    # Companion keys are formed by appending a suffix to the COMPLETE filename,
    # never by replacing its extension. The sidecar for `a.mp4` is `a.mp4.json`.
    def sidecar_key_for(media_key) = "#{media_key}.json"

    # SPEC's reindex rule 1: "Every key ending in .json is a sidecar. Stripping
    # that suffix yields the media key it describes."
    def sidecar?(key) = extension_of(key) == ".json"

    def media_key_for_sidecar(sidecar_key)
      sidecar_key.to_s.sub(/\.json\z/i, "")
    end

    # SPEC's reindex rule 2: a thumbnail is a key formed by appending an image
    # extension to ANOTHER KEY PRESENT IN THE BUCKET. Presence is what makes it
    # a thumbnail rather than standalone media -- which is why this takes the
    # whole key set. `img3.jpg.jpg` is the thumbnail of `img3.jpg`.
    def thumbnail_of(key, all_keys)
      ext = extension_of(key)
      return nil unless THUMBNAIL_EXTS.include?(ext)
      candidate = key.to_s[0...-ext.length]
      all_keys.include?(candidate) ? candidate : nil
    end

    # SPEC: "A reader must never inspect file contents to determine format.
    # The extension is the answer." So this is a lookup, not a sniff -- which
    # is also why it does not use Marcel.
    #
    # Rack ships a table covering the common web types; these are the ones a
    # family video library hits that Rack does not know or gets wrong.
    MIME_OVERRIDES = {
      ".heic" => "image/heic",
      ".heif" => "image/heif",
      ".mov"  => "video/quicktime",
      ".m4v"  => "video/x-m4v",
      ".mts"  => "video/mp2t",
      ".m2ts" => "video/mp2t",
      ".3gp"  => "video/3gpp"
    }.freeze

    def mime_type(key)
      ext = extension_of(key)
      return "application/octet-stream" if ext.empty?
      MIME_OVERRIDES[ext] || Rack::Mime.mime_type(ext, "application/octet-stream")
    end

    # A human label for the format, for the download card.
    def format_label(key)
      ext = extension_of(key)
      return "file" if ext.empty?
      ext.delete_prefix(".").upcase
    end
  end
end
