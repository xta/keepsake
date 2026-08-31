module Keepsake
  # Presets for the S3-compatible services people actually use.
  #
  # These exist for two reasons. Usability: nobody should have to hand-assemble
  # `https://s3.us-east-001.backblazeb2.com`. And safety: a preset builds its
  # own endpoint from a region or account id, so the only mode that ever
  # accepts a free-form URL from a user is "other".
  module Provider
    module_function

    NAMES = %w[aws b2 r2 other local].freeze

    # Selectable in a real deployment. `local` is a development-only backend
    # (a directory standing in for a bucket), the same trick the Python CLI
    # uses so its tests need no network and no credentials.
    PUBLIC_NAMES = %w[aws b2 r2 other].freeze

    def selectable
      Rails.env.local? ? NAMES : PUBLIC_NAMES
    end

    def endpoint_for(provider, region:, account_id: nil, endpoint: nil)
      case provider
      when "aws"
        region.present? ? "https://s3.#{region}.amazonaws.com" : nil
      when "b2"
        region.present? ? "https://s3.#{region}.backblazeb2.com" : nil
      when "r2"
        # Cloudflare's endpoint is per account, not per region.
        account_id.present? ? "https://#{account_id}.r2.cloudflarestorage.com" : endpoint
      else
        endpoint
      end
    end

    # A region is a bare token like `us-west-001`. People reasonably paste the
    # whole endpoint, or the `s3.us-west-001` prefix from it, because that is
    # the string they are looking at in their provider's console. Recover the
    # region from any of those rather than handing the SDK something it will
    # reject with "region was not a valid DNS name".
    def normalize_region(value)
      token = value.to_s.strip.downcase
      return token unless token.include?(".")

      token = token.sub(%r{\Ahttps?://}, "").split("/").first.to_s
      parts = token.split(".")
      parts.shift if parts.first == "s3"
      parts.first.to_s
    end

    # SigV4 needs a region even when the endpoint already implies one.
    def region_for(provider, region:, endpoint: nil)
      region = normalize_region(region)
      case provider
      when "r2"
        # Cloudflare ignores region but the signer still requires a value.
        "auto"
      when "b2"
        region.presence || region_from_endpoint(endpoint) || "us-east-005"
      when "local"
        region.presence || "local"
      else
        region.presence || region_from_endpoint(endpoint) || "us-east-1"
      end
    end

    # `https://s3.us-east-001.backblazeb2.com` -> `us-east-001`
    def region_from_endpoint(endpoint)
      return nil if endpoint.blank?
      host = begin
        URI.parse(endpoint).host.to_s
      rescue URI::InvalidURIError
        ""
      end
      parts = host.split(".")
      return parts[1] if parts.length >= 3 && parts[0] == "s3"
      nil
    end

    # Drives the form: which fields to show, and how to explain them.
    def form_metadata
      {
        "aws" => {
          label: "Amazon S3",
          fields: %w[region bucket],
          region_label: "Region",
          region_hint: "e.g. us-east-1",
          key_help: "An IAM user with s3:GetObject and s3:ListBucket on this bucket."
        },
        "b2" => {
          label: "Backblaze B2",
          fields: %w[region bucket],
          region_label: "S3 endpoint or region",
          region_hint: "Endpoint or region. Either works.",
          key_help: "An Application Key limited to this bucket, with listFiles and readFiles. Not deleteFiles."
        },
        "r2" => {
          label: "Cloudflare R2",
          fields: %w[account_id bucket],
          region_hint: "R2 has no regions.",
          key_help: "An R2 API token for this bucket with Object Read."
        },
        "other" => {
          label: "Other S3-compatible",
          fields: %w[endpoint region bucket],
          region_label: "Region",
          region_hint: "Whatever your provider signs with. Try us-east-1.",
          key_help: "A read-only key for this bucket, if your provider does those."
        },
        "local" => {
          label: "Local directory (development only)",
          fields: %w[bucket],
          region_hint: "Not used.",
          key_help: "Bucket is an absolute path to a directory on this machine."
        }
      }
    end
  end
end
