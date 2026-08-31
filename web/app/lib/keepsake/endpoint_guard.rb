module Keepsake
  # The single check standing between "a user typed a URL" and "our server
  # makes a request to it".
  #
  # Without this, a multi-tenant app that stores arbitrary endpoints is a
  # request generator pointed at whatever the host can reach: cloud metadata
  # at 169.254.169.254, 127.0.0.1, and the Postgres accessory sharing the
  # container network.
  #
  # WHAT THIS DOES NOT CLOSE: a TOCTOU window. We resolve the hostname, decide
  # it is public, and then the AWS SDK resolves it again independently -- a DNS
  # record that changes in between defeats the check. Closing it properly means
  # egress filtering on the host, or pinning the connection to the address we
  # validated. Treat this as a strong speed bump, not a boundary.
  module EndpointGuard
    class Rejected < StandardError; end

    module_function

    BLOCKED_V4 = %w[
      0.0.0.0/8 10.0.0.0/8 100.64.0.0/10 127.0.0.0/8 169.254.0.0/16
      172.16.0.0/12 192.0.0.0/24 192.0.2.0/24 192.168.0.0/16 198.18.0.0/15
      198.51.100.0/24 203.0.113.0/24 224.0.0.0/4 240.0.0.0/4
    ].map { |c| IPAddr.new(c) }.freeze

    BLOCKED_V6 = %w[
      ::/128 ::1/128 fc00::/7 fe80::/10 ff00::/8 2001:db8::/32
    ].map { |c| IPAddr.new(c) }.freeze

    def validate!(endpoint)
      uri = parse(endpoint)

      unless uri.scheme == "https"
        raise Rejected, "must use https (got #{uri.scheme.presence || 'no scheme'})"
      end
      raise Rejected, "must include a hostname" if uri.host.blank?

      addresses = resolve(uri.host)
      raise Rejected, "hostname does not resolve" if addresses.empty?

      blocked = addresses.select { |ip| blocked?(ip) }
      if blocked.any?
        raise Rejected, "resolves to a private or reserved address (#{blocked.first}), which this server will not connect to"
      end

      uri.to_s
    end

    def safe?(endpoint)
      validate!(endpoint)
      true
    rescue Rejected
      false
    end

    def parse(endpoint)
      URI.parse(endpoint.to_s.strip)
    rescue URI::InvalidURIError
      raise Rejected, "is not a valid URL"
    end

    def resolve(host)
      # A literal address needs no lookup, and Resolv would not do one.
      return [ IPAddr.new(host) ] if literal_ip?(host)

      Resolv.getaddresses(host).filter_map do |a|
        begin
          IPAddr.new(a)
        rescue IPAddr::InvalidAddressError
          nil
        end
      end
    rescue Resolv::ResolvError, IPAddr::InvalidAddressError
      []
    end

    def literal_ip?(host)
      IPAddr.new(host)
      true
    rescue IPAddr::InvalidAddressError
      false
    end

    def blocked?(ip)
      list = ip.ipv4? ? BLOCKED_V4 : BLOCKED_V6
      return true if list.any? { |net| net.include?(ip) }
      # An IPv6-mapped IPv4 address (::ffff:127.0.0.1) must be judged by the
      # v4 rules, or the loopback check is trivially bypassed.
      if ip.ipv6? && ip.ipv4_mapped?
        return BLOCKED_V4.any? { |net| net.include?(ip.native) }
      end
      false
    end
  end
end
