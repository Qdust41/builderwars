"""Web app hosting: a private S3 bucket behind CloudFront, plus the API on the same origin.

- ``/*`` serves the built single-page app (``apps/web/dist``) from S3 through origin access
  control. Paths without a file extension are client-side routes and get ``index.html``
  (a viewer-request function, not distribution-wide error pages, so API 403/404s pass through).
- ``/api/*`` goes to the HTTP API with caching off and every viewer header except ``Host``
  (so the Cognito ``Authorization`` header reaches the JWT authorizer). A function strips the
  ``/api`` prefix, matching the Vite dev proxy, so the browser never makes cross-origin API calls.
- With ``config.web_domain`` set, an ACM certificate (DNS-validated) and the alternate domain
  name are added. DNS is hosted in Cloudflare, so the validation and ``CNAME`` records are added
  there by hand (docs/deployment-guide.md, "Web app on your domain").

The site is uploaded from ``apps/web/dist`` at deploy time. Build it first (``scripts/
build_web_prod.sh``); when it is missing (CI synth, template tests) the upload is left out.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from aws_cdk import Annotations, CfnOutput, Fn, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_certificatemanager as acm
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_deployment as s3deploy
from config import EnvConfig
from constructs import Construct

WEB_DIST = Path(__file__).resolve().parents[2] / "apps" / "web" / "dist"

# Client-side routes (last path segment has no ".") load the app shell.
SPA_ROUTING_JS = r"""
function handler(event) {
  var request = event.request;
  if (!/\/[^\/]*\.[^\/]*$/.test(request.uri)) {
    request.uri = '/index.html';
  }
  return request;
}
"""

# /api/projects -> /projects, like the Vite dev proxy's rewrite.
STRIP_API_PREFIX_JS = r"""
function handler(event) {
  var request = event.request;
  request.uri = request.uri.replace(/^\/api(?=\/|$)/, '') || '/';
  return request;
}
"""


class WebStack(Stack):
    def __init__(
        self,
        scope: Construct,
        cid: str,
        *,
        config: EnvConfig,
        http_api: apigw.HttpApi,
        **kw: Any,
    ) -> None:
        super().__init__(scope, cid, **kw)

        # Only build output lives here, so it is safe to delete with the stack.
        site_bucket = s3.Bucket(
            self,
            "Site",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            object_ownership=s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        spa_routing = cloudfront.Function(
            self,
            "SpaRouting",
            code=cloudfront.FunctionCode.from_inline(SPA_ROUTING_JS),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
            comment="Serve index.html for client-side routes",
        )
        strip_api_prefix = cloudfront.Function(
            self,
            "StripApiPrefix",
            code=cloudfront.FunctionCode.from_inline(STRIP_API_PREFIX_JS),
            runtime=cloudfront.FunctionRuntime.JS_2_0,
            comment="Remove the /api prefix before forwarding to API Gateway",
        )

        # https://<id>.execute-api.<region>.amazonaws.com -> <id>.execute-api.<region>.amazonaws.com
        api_domain = Fn.select(2, Fn.split("/", http_api.api_endpoint))

        certificate = (
            acm.Certificate(
                self,
                "Certificate",
                domain_name=config.web_domain,
                validation=acm.CertificateValidation.from_dns(),
            )
            if config.web_domain
            else None
        )

        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment=config.resource_name("web"),
            default_root_object="index.html",
            domain_names=[config.web_domain] if config.web_domain else None,
            certificate=certificate,
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            http_version=cloudfront.HttpVersion.HTTP2_AND_3,
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(site_bucket),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
                function_associations=[
                    cloudfront.FunctionAssociation(
                        function=spa_routing,
                        event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                    )
                ],
            ),
            additional_behaviors={
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origins.HttpOrigin(
                        api_domain, protocol_policy=cloudfront.OriginProtocolPolicy.HTTPS_ONLY
                    ),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=(
                        cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER
                    ),
                    function_associations=[
                        cloudfront.FunctionAssociation(
                            function=strip_api_prefix,
                            event_type=cloudfront.FunctionEventType.VIEWER_REQUEST,
                        )
                    ],
                )
            },
        )

        if (WEB_DIST / "index.html").is_file():
            s3deploy.BucketDeployment(
                self,
                "DeploySite",
                sources=[s3deploy.Source.asset(str(WEB_DIST))],
                destination_bucket=site_bucket,
                # Hashed assets revalidate cheaply; index.html must never go stale.
                cache_control=[
                    s3deploy.CacheControl.from_string("public, max-age=0, must-revalidate")
                ],
                distribution=distribution,
                distribution_paths=["/*"],
                memory_limit=512,
            )
        else:
            Annotations.of(self).add_warning_v2(
                "builderwars:web-dist-missing",
                f"{WEB_DIST} has no build; the site upload is skipped "
                "(run scripts/build_web_prod.sh before deploying).",
            )

        CfnOutput(
            self,
            "WebUrl",
            value=f"https://{config.web_domain or distribution.distribution_domain_name}",
        )
        # The Cloudflare CNAME target for config.web_domain.
        CfnOutput(self, "DistributionDomainName", value=distribution.distribution_domain_name)
        CfnOutput(self, "DistributionId", value=distribution.distribution_id)
